"""The Square API client seam and its httpx implementation.

``SquareApi`` is the Protocol the adapter drives (tests inject a fake that returns canned
Square JSON, so no network is needed). ``SquarePuller`` is the httpx implementation for
sandbox/production. Vendor HTTP failures are mapped to stable
:class:`ConnectorReasonCode`s (never raw vendor text) and raised as
``ConnectorExtractError`` / ``ConnectorAuthError``.

Transport hardening (Square S1):

- Rate limits (HTTP 429) and transient server errors (500/502/503/504) plus transport
  errors are retried with bounded exponential backoff + jitter, capped at a hard attempt
  limit. Square documents backoff-with-jitter for 429 and does NOT document a
  ``Retry-After`` header; we honour it defensively when present, otherwise compute the
  delay ourselves. The wait is done through an injectable ``sleep`` so tests use a fake
  clock (no real sleeps).
- Non-retryable ``4xx`` (other than 401/403) raise a typed ``ConnectorExtractError``
  carrying a bounded response-body excerpt in ``detail`` (never a raw reason code); the
  excerpt aids debugging without leaking our access token, which Square never echoes.
- 401/403 raise ``ConnectorAuthError`` immediately (no retry).
- Cursor pagination: ``list_catalog`` / ``search_orders`` return a single page + the next
  cursor (the SDK pipeline drives exhaustion across runs); ``batch_inventory`` returns a
  complete map, so it exhausts its own cursor internally.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from thalamus_connector_sdk import ConnectorAuthError, ConnectorExtractError, ConnectorReasonCode

# Retry / backoff policy (module constants so the bounds are auditable in one place).
_MAX_ATTEMPTS = 5
_BACKOFF_BASE_SECONDS = 0.5
_BACKOFF_CAP_SECONDS = 20.0
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
# Bounded body excerpt carried in ConnectorError.detail on non-retryable / exhausted HTTP
# failures. Kept small so a large error page never bloats logs.
_EXCERPT_MAX_CHARS = 512
# Defensive cap on batch_inventory's internal cursor loop (a misbehaving vendor cursor
# must not spin forever). Far above any realistic inventory page count.
_MAX_INVENTORY_PAGES = 1000


@dataclass(frozen=True)
class CatalogPage:
    """One page of catalog: ITEM objects (variations nested), a category id->name map,
    and the next cursor."""

    items: list[dict[str, Any]]
    categories: dict[str, str]
    next_cursor: str | None


@dataclass(frozen=True)
class OrdersPage:
    """One page of orders plus the next cursor."""

    orders: list[dict[str, Any]]
    next_cursor: str | None


class SquareApi(Protocol):
    """The Square operations the adapter needs (cursor incremental)."""

    def list_locations(self, token: str) -> list[dict[str, Any]]: ...

    def list_catalog(self, token: str, cursor: str | None) -> CatalogPage: ...

    def batch_inventory(
        self, token: str, *, catalog_object_ids: Sequence[str], location_ids: Sequence[str]
    ) -> dict[str, str]: ...

    def search_orders(self, token: str, *, location_ids: Sequence[str], cursor: str | None) -> OrdersPage: ...


def _excerpt(response: httpx.Response) -> str | None:
    """A bounded, stripped excerpt of the response body for ``detail`` (never None-empty)."""
    text = response.text.strip()
    if not text:
        return None
    return text[:_EXCERPT_MAX_CHARS]


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Square does not document a Retry-After header; honour it defensively when the value
    is a plain integer number of seconds. HTTP-date form is not parsed (never sent)."""
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


class SquarePuller:
    """httpx-backed Square client (sandbox or production share the same shapes)."""

    def __init__(
        self,
        *,
        base_url: str,
        api_version: str,
        client: httpx.Client | None = None,
        max_attempts: int = _MAX_ATTEMPTS,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_version = api_version
        self._client = client or httpx.Client(timeout=30.0)
        self._max_attempts = max_attempts
        # Injectable so unit tests use a fake clock and a deterministic jitter source; no
        # real sleeping in tests. In production these default to time.sleep + a real RNG.
        self._sleep = sleep
        self._rng = rng or random.Random()

    def _backoff_delay(self, attempt: int, retry_after: float | None) -> float:
        """Seconds to wait before the next attempt. Honours Retry-After (bounded) when the
        vendor sent one; otherwise bounded exponential backoff with equal jitter."""
        if retry_after is not None:
            return min(retry_after, _BACKOFF_CAP_SECONDS)
        # float() pins the type: int ** int is inferred as Any by the type checker.
        exponential = _BACKOFF_BASE_SECONDS * float(2 ** (attempt - 1))
        capped = min(exponential, _BACKOFF_CAP_SECONDS)
        half = capped / 2
        return half + self._rng.uniform(0, half)

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Square-Version": self._api_version,
            "Content-Type": "application/json",
        }

    def _get(self, token: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("GET", token, path, params=params)

    def _post(self, token: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", token, path, json=body)

    def _request(
        self,
        method: str,
        token: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        for attempt in range(1, self._max_attempts + 1):
            last = attempt == self._max_attempts
            try:
                response = self._client.request(
                    method, url, headers=self._headers(token), params=params, json=json
                )
            except httpx.HTTPError as exc:
                # Transport-level failure (connect/read/timeout): transient, retry.
                if not last:
                    self._sleep(self._backoff_delay(attempt, None))
                    continue
                raise ConnectorExtractError(
                    f"Square request failed after {attempt} attempts: {type(exc).__name__}",
                    reason=ConnectorReasonCode.VENDOR_UNAVAILABLE,
                ) from exc

            status = response.status_code
            if status < 400:
                payload: dict[str, Any] = response.json()
                return payload

            if status in (401, 403):
                raise ConnectorAuthError(
                    f"Square returned HTTP {status}",
                    reason=ConnectorReasonCode.AUTH_FAILED,
                    detail=_excerpt(response),
                )

            if status in _RETRYABLE_STATUS:
                if not last:
                    self._sleep(self._backoff_delay(attempt, _parse_retry_after(response)))
                    continue
                # Attempt cap reached: surface a typed error. 429 stays RATE_LIMITED;
                # transient 5xx becomes VENDOR_UNAVAILABLE.
                reason = (
                    ConnectorReasonCode.RATE_LIMITED
                    if status == 429
                    else ConnectorReasonCode.VENDOR_UNAVAILABLE
                )
                raise ConnectorExtractError(
                    f"Square returned HTTP {status} after {attempt} attempts",
                    reason=reason,
                    detail=_excerpt(response),
                )

            # Non-retryable status (other 4xx, and non-transient 5xx like 501): no
            # dedicated client-error reason code exists, so map to VENDOR_UNAVAILABLE and
            # carry the specifics in the bounded detail excerpt.
            raise ConnectorExtractError(
                f"Square returned HTTP {status}",
                reason=ConnectorReasonCode.VENDOR_UNAVAILABLE,
                detail=_excerpt(response),
            )

        # Unreachable: the loop returns or raises on every path (max_attempts >= 1).
        raise ConnectorExtractError(
            "Square request loop exhausted unexpectedly",
            reason=ConnectorReasonCode.VENDOR_UNAVAILABLE,
        )

    def list_locations(self, token: str) -> list[dict[str, Any]]:
        data = self._get(token, "/v2/locations")
        locations: list[dict[str, Any]] = data.get("locations") or []
        return locations

    def list_catalog(self, token: str, cursor: str | None) -> CatalogPage:
        params: dict[str, Any] = {"types": "ITEM,CATEGORY"}
        if cursor:
            params["cursor"] = cursor
        data = self._get(token, "/v2/catalog/list", params=params)
        objects: list[dict[str, Any]] = data.get("objects") or []
        items = [obj for obj in objects if obj.get("type") == "ITEM"]
        categories = {
            str(obj.get("id")): str((obj.get("category_data") or {}).get("name") or "")
            for obj in objects
            if obj.get("type") == "CATEGORY"
        }
        return CatalogPage(items=items, categories=categories, next_cursor=data.get("cursor"))

    def batch_inventory(
        self, token: str, *, catalog_object_ids: Sequence[str], location_ids: Sequence[str]
    ) -> dict[str, str]:
        if not catalog_object_ids:
            return {}
        counts: dict[str, str] = {}
        cursor: str | None = None
        # This method's contract is a COMPLETE map, so it exhausts the inventory cursor
        # internally (unlike list_catalog / search_orders, whose single-page contract
        # lets the SDK pipeline drive exhaustion across runs).
        for _ in range(_MAX_INVENTORY_PAGES):
            body: dict[str, Any] = {
                "catalog_object_ids": list(catalog_object_ids),
                "location_ids": list(location_ids),
                "states": ["IN_STOCK"],
            }
            if cursor:
                body["cursor"] = cursor
            data = self._post(token, "/v2/inventory/counts/batch-retrieve", body)
            for count in data.get("counts") or []:
                object_id = count.get("catalog_object_id")
                quantity = count.get("quantity")
                if isinstance(object_id, str) and quantity is not None:
                    counts[object_id] = str(quantity)
            cursor = data.get("cursor")
            if not cursor:
                return counts
        raise ConnectorExtractError(
            f"Square inventory pagination exceeded {_MAX_INVENTORY_PAGES} pages",
            reason=ConnectorReasonCode.VENDOR_UNAVAILABLE,
        )

    def search_orders(self, token: str, *, location_ids: Sequence[str], cursor: str | None) -> OrdersPage:
        body: dict[str, Any] = {"location_ids": list(location_ids), "limit": 500}
        if cursor:
            body["cursor"] = cursor
        data = self._post(token, "/v2/orders/search", body)
        orders: list[dict[str, Any]] = data.get("orders") or []
        return OrdersPage(orders=orders, next_cursor=data.get("cursor"))
