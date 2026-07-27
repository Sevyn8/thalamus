"""The Clover API client seam and its httpx implementation.

``CloverApi`` is the Protocol the adapter drives (tests inject a fake returning canned
Clover JSON, so no network is needed). ``CloverPuller`` is the httpx implementation for
sandbox/production. Vendor HTTP failures map to stable :class:`ConnectorReasonCode`s
(never raw vendor text) and raise ``ConnectorExtractError`` / ``ConnectorAuthError``.

Every path is ``/v3/merchants/{merchant_id}/...`` - Clover's API is merchant-scoped in the
URL, which is why the adapter needs a merchant id alongside the token on every call.

--- WHY STOCK IS A SEPARATE CALL, AND MUST STAY ONE ---------------------------------------

Clover's ``expand`` parameter FAILS OPEN: ``?expand=bogusfield`` returns HTTP 200 and simply
expands nothing (confirmed against the live sandbox 2026-07-27). A typo'd or renamed expand
therefore produces a perfectly successful-looking response with the data silently missing.
That is only safe where we can DETECT it, and the two expansions differ:

- ``expand=categories`` IS verifiable by key presence. When expansion works EVERY item
  carries a ``categories`` key - an uncategorised item shows ``{"elements": []}``, the key
  present and empty. Without expansion the key is absent entirely. So "no item has the key
  on a non-empty page" cleanly means the expand failed, and is distinguishable from "this
  merchant categorises nothing". :func:`_require_expansion` enforces exactly that.

- ``expand=itemStock`` is NOT verifiable by key presence. An UNTRACKED item omits the key
  even when the expansion is working correctly, so absence is legitimate and proves nothing.
  A silent expand failure would be indistinguishable from a merchant who tracks no stock,
  and we would ship stock-less rows believing them correct.

Stock is therefore fetched as its own ``/item_stocks`` COLLECTION and joined client-side. A
collection is self-evidencing: we can count it. DO NOT "optimise" this into
``expand=itemStock`` on the items call - it would trade a detectable failure for an
undetectable one. (It also mirrors the Square lane, where inventory is a separate call
joined in ``mapping.py``.)

--- transport hardening (mirrors SquarePuller's S1) ----------------------------------------

Rate limits (HTTP 429) and transient server errors (500/502/503/504) plus transport errors
are retried with bounded exponential backoff + jitter, capped at a hard attempt limit.
Clover sent NO rate-limit or Retry-After headers on any probed response, even under a
burst, so ``Retry-After`` is honoured DEFENSIVELY when present and otherwise the delay is
computed. Clover rate-limits per merchant AND per app AND per endpoint, so the posture
matters more here than on Square. The wait goes through an injectable ``sleep`` so tests use
a fake clock (no real sleeps).

Pagination is OFFSET-based, not cursored: the envelope is ``{"elements": [...], "href": ...}``
with no continuation token, so the end of a collection is a SHORT PAGE. ``limit`` is capped
at 1000 by the vendor (400 above it) and ``offset`` must be >= 0 (400 below).
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from thalamus_clover.config import API_PATH_VERSION, PAGE_LIMIT_MAX
from thalamus_connector_sdk import (
    RATE_LIMIT_THROTTLED,
    ConnectorAuthError,
    ConnectorExtractError,
    ConnectorReasonCode,
)

# Retry / backoff policy (module constants so the bounds are auditable in one place).
_MAX_ATTEMPTS = 5
_BACKOFF_BASE_SECONDS = 0.5
_BACKOFF_CAP_SECONDS = 20.0
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
# Bounded body excerpt carried in ConnectorError.detail on non-retryable / exhausted HTTP
# failures. Clover's error envelope is {"message": "..."}, which is small; the cap guards
# against an unexpected HTML error page bloating logs.
_EXCERPT_MAX_CHARS = 512
# Defensive cap on the internally-exhausted collections (categories, item_stocks). A
# misbehaving vendor offset must not spin forever. Far above any realistic merchant.
_MAX_COLLECTION_PAGES = 1000


@dataclass(frozen=True)
class ItemPage:
    """One page of items plus the next offset cursor (None at the end of the collection)."""

    items: list[dict[str, Any]]
    next_cursor: str | None


class CloverApi(Protocol):
    """The Clover operations the adapter needs (offset incremental)."""

    def rate_limit_state(self) -> str | None: ...

    def get_merchant(self, token: str, merchant_id: str) -> dict[str, Any]: ...

    def list_items(self, token: str, merchant_id: str, cursor: str | None) -> ItemPage: ...

    def list_categories(self, token: str, merchant_id: str) -> dict[str, dict[str, Any]]: ...

    def list_item_stocks(self, token: str, merchant_id: str) -> dict[str, str]: ...


def _excerpt(response: httpx.Response) -> str | None:
    """A bounded, stripped excerpt of the response body for ``detail`` (never None-empty)."""
    text = response.text.strip()
    if not text:
        return None
    return text[:_EXCERPT_MAX_CHARS]


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Clover sent no Retry-After on any probed response; honour it defensively when the
    value is a plain integer number of seconds. HTTP-date form is not parsed."""
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def _parse_offset(cursor: str | None) -> int:
    """The cursor IS the offset, as opaque text (the SDK treats cursors as opaque)."""
    if not cursor:
        return 0
    try:
        offset = int(cursor)
    except ValueError as exc:
        raise ConnectorExtractError(
            "Clover cursor is not an offset; the cursor was minted by a different connector",
            reason=ConnectorReasonCode.SCHEMA_UNRECOGNIZED,
        ) from exc
    return max(offset, 0)


def _require_expansion(elements: Sequence[Mapping[str, Any]], key: str) -> None:
    """Fail loudly when a requested expansion silently did not happen.

    Valid ONLY for expansions whose key is present-when-working even if empty (see the
    module docstring). A non-empty page where NO element carries ``key`` means the expand
    was ignored - never a merchant with nothing to expand, because that case still yields
    the key with an empty envelope.
    """
    if not elements:
        return  # an empty page proves nothing either way
    if any(key in element for element in elements):
        return
    raise ConnectorExtractError(
        f"Clover ignored expand={key!r}: no element on a non-empty page carries the key. "
        "Clover returns HTTP 200 for an unrecognised expand, so this would otherwise look "
        "like a merchant with no data for that relation",
        reason=ConnectorReasonCode.SCHEMA_UNRECOGNIZED,
    )


class CloverPuller:
    """httpx-backed Clover client (sandbox or production share the same shapes)."""

    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.Client | None = None,
        max_attempts: int = _MAX_ATTEMPTS,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        page_limit: int = PAGE_LIMIT_MAX,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=30.0)
        self._max_attempts = max_attempts
        # Injectable so unit tests use a fake clock and a deterministic jitter source; no
        # real sleeping in tests. In production these default to time.sleep + a real RNG.
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._page_limit = min(page_limit, PAGE_LIMIT_MAX)
        # Set once a 429 has been ABSORBED (retried and recovered from) by this instance.
        # Monotonic for the instance's life, which is correct because one process runs
        # exactly one trigger today (the Cloud Run Job model). A long-lived transport
        # driving many triggers through one puller must construct one per run or add a reset.
        self._absorbed_rate_limit = False

    def rate_limit_state(self) -> str | None:
        """The coarse posture for ``telemetry.connector_health.rate_limit_state`` (D116).

        ``RATE_LIMIT_THROTTLED`` once this instance has absorbed a 429, else None. None is a
        positive "no rate-limit response observed", which is what clears a stored posture.
        """
        return RATE_LIMIT_THROTTLED if self._absorbed_rate_limit else None

    # -- transport --------------------------------------------------------------

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

    def _merchant_path(self, merchant_id: str, suffix: str = "") -> str:
        return f"/{API_PATH_VERSION}/merchants/{merchant_id}{suffix}"

    def _get(self, token: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        for attempt in range(1, self._max_attempts + 1):
            last = attempt == self._max_attempts
            try:
                response = self._client.get(url, headers=headers, params=params)
            except httpx.HTTPError as exc:
                # Transport-level failure (connect/read/timeout): transient, retry.
                if not last:
                    self._sleep(self._backoff_delay(attempt, None))
                    continue
                raise ConnectorExtractError(
                    f"Clover request failed after {attempt} attempts: {type(exc).__name__}",
                    reason=ConnectorReasonCode.VENDOR_UNAVAILABLE,
                ) from exc

            status = response.status_code
            if status < 400:
                payload: dict[str, Any] = response.json()
                return payload

            if status in (401, 403):
                raise ConnectorAuthError(
                    f"Clover returned HTTP {status}",
                    reason=ConnectorReasonCode.AUTH_FAILED,
                    detail=_excerpt(response),
                )

            if status in _RETRYABLE_STATUS:
                if not last:
                    # A 429 we are about to retry is an ABSORBED rate limit: record the
                    # posture before sleeping. A retryable 5xx is not throttling.
                    if status == 429:
                        self._absorbed_rate_limit = True
                    self._sleep(self._backoff_delay(attempt, _parse_retry_after(response)))
                    continue
                reason = (
                    ConnectorReasonCode.RATE_LIMITED
                    if status == 429
                    else ConnectorReasonCode.VENDOR_UNAVAILABLE
                )
                raise ConnectorExtractError(
                    f"Clover returned HTTP {status} after {attempt} attempts",
                    reason=reason,
                    detail=_excerpt(response),
                )

            # Non-retryable status (other 4xx, non-transient 5xx): no dedicated client-error
            # reason code exists, so map to VENDOR_UNAVAILABLE and carry the specifics in
            # the bounded detail excerpt (Clover's envelope is {"message": "..."}).
            raise ConnectorExtractError(
                f"Clover returned HTTP {status}",
                reason=ConnectorReasonCode.VENDOR_UNAVAILABLE,
                detail=_excerpt(response),
            )

        # Unreachable: the loop returns or raises on every path (max_attempts >= 1).
        raise ConnectorExtractError(
            "Clover request loop exhausted unexpectedly",
            reason=ConnectorReasonCode.VENDOR_UNAVAILABLE,
        )

    def _elements(self, data: Mapping[str, Any]) -> list[dict[str, Any]]:
        elements = data.get("elements")
        return [e for e in elements if isinstance(e, dict)] if isinstance(elements, list) else []

    # -- operations -------------------------------------------------------------

    def get_merchant(self, token: str, merchant_id: str) -> dict[str, Any]:
        """The merchant, with ``properties`` expanded (that is where defaultCurrency lives).

        Doubles as the authenticate-time token validation: a bad token is 401 here.
        """
        return self._get(token, self._merchant_path(merchant_id), {"expand": "properties"})

    def list_items(self, token: str, merchant_id: str, cursor: str | None) -> ItemPage:
        """One page of items with categories expanded; the cursor is the offset.

        A SHORT page ends the collection (there is no continuation token), so ``next_cursor``
        is None whenever fewer than ``page_limit`` elements come back.
        """
        offset = _parse_offset(cursor)
        data = self._get(
            token,
            self._merchant_path(merchant_id, "/items"),
            {"expand": "categories", "limit": self._page_limit, "offset": offset},
        )
        items = self._elements(data)
        # Guard the expand: see the module docstring. Safe for categories, and ONLY for
        # categories, because the key is present-when-working even for an uncategorised item.
        _require_expansion(items, "categories")
        next_cursor = str(offset + self._page_limit) if len(items) == self._page_limit else None
        return ItemPage(items=items, next_cursor=next_cursor)

    def list_categories(self, token: str, merchant_id: str) -> dict[str, dict[str, Any]]:
        """The merchant's categories keyed by id (the authoritative source of sortOrder).

        Exhausts its own offset internally: the contract is a COMPLETE map, unlike
        ``list_items`` whose single-page contract lets the SDK pipeline drive exhaustion
        across runs.
        """
        return {
            str(row["id"]): row
            for row in self._exhaust(token, self._merchant_path(merchant_id, "/categories"))
            if isinstance(row.get("id"), str)
        }

    def list_item_stocks(self, token: str, merchant_id: str) -> dict[str, str]:
        """Tracked stock levels keyed by item id. Untracked items are simply ABSENT.

        A separate collection rather than ``expand=itemStock`` - see the module docstring;
        this is the detectable-failure choice, not a redundant call. Absence here is what
        makes ``stock_qty`` omitted rather than zero downstream.
        """
        stocks: dict[str, str] = {}
        for row in self._exhaust(token, self._merchant_path(merchant_id, "/item_stocks")):
            item_id = (row.get("item") or {}).get("id")
            quantity = row.get("quantity")
            # A stock record can exist as a stub with NO quantity (observed on the sandbox);
            # that is still "not counted", so it must not become a zero.
            if isinstance(item_id, str) and quantity is not None:
                stocks[item_id] = str(quantity)
        return stocks

    def _exhaust(self, token: str, path: str) -> list[dict[str, Any]]:
        """Page a collection to completion by offset, bounded by a defensive page cap."""
        rows: list[dict[str, Any]] = []
        offset = 0
        for _ in range(_MAX_COLLECTION_PAGES):
            data = self._get(token, path, {"limit": self._page_limit, "offset": offset})
            page = self._elements(data)
            rows.extend(page)
            if len(page) < self._page_limit:
                return rows
            offset += self._page_limit
        raise ConnectorExtractError(
            f"Clover collection {path} exceeded {_MAX_COLLECTION_PAGES} pages",
            reason=ConnectorReasonCode.VENDOR_UNAVAILABLE,
        )
