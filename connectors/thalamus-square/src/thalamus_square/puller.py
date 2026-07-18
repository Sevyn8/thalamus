"""The Square API client seam and its httpx implementation.

``SquareApi`` is the Protocol the adapter drives (tests inject a fake that returns canned
Square JSON, so no network is needed). ``SquarePuller`` is the httpx implementation for
sandbox/production. Vendor HTTP failures are mapped to stable
:class:`ConnectorReasonCode`s (never raw vendor text) and raised as
``ConnectorExtractError`` / ``ConnectorAuthError``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from thalamus_connector_sdk import ConnectorAuthError, ConnectorExtractError, ConnectorReasonCode


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


def _reason_for_status(status_code: int) -> ConnectorReasonCode:
    if status_code in (401, 403):
        return ConnectorReasonCode.AUTH_FAILED
    if status_code == 429:
        return ConnectorReasonCode.RATE_LIMITED
    return ConnectorReasonCode.VENDOR_UNAVAILABLE


class SquarePuller:
    """httpx-backed Square client (sandbox or production share the same shapes)."""

    def __init__(self, *, base_url: str, api_version: str, client: httpx.Client | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_version = api_version
        self._client = client or httpx.Client(timeout=30.0)

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
        try:
            response = self._client.request(
                method, url, headers=self._headers(token), params=params, json=json
            )
        except httpx.HTTPError as exc:
            raise ConnectorExtractError(
                f"Square request failed: {type(exc).__name__}",
                reason=ConnectorReasonCode.VENDOR_UNAVAILABLE,
            ) from exc
        if response.status_code >= 400:
            reason = _reason_for_status(response.status_code)
            message = f"Square returned HTTP {response.status_code}"
            if reason is ConnectorReasonCode.AUTH_FAILED:
                raise ConnectorAuthError(message, reason=reason)
            raise ConnectorExtractError(message, reason=reason)
        payload: dict[str, Any] = response.json()
        return payload

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
        body: dict[str, Any] = {
            "catalog_object_ids": list(catalog_object_ids),
            "location_ids": list(location_ids),
            "states": ["IN_STOCK"],
        }
        data = self._post(token, "/v2/inventory/counts/batch-retrieve", body)
        counts: dict[str, str] = {}
        for count in data.get("counts") or []:
            object_id = count.get("catalog_object_id")
            quantity = count.get("quantity")
            if isinstance(object_id, str) and quantity is not None:
                counts[object_id] = str(quantity)
        return counts

    def search_orders(self, token: str, *, location_ids: Sequence[str], cursor: str | None) -> OrdersPage:
        body: dict[str, Any] = {"location_ids": list(location_ids), "limit": 500}
        if cursor:
            body["cursor"] = cursor
        data = self._post(token, "/v2/orders/search", body)
        orders: list[dict[str, Any]] = data.get("orders") or []
        return OrdersPage(orders=orders, next_cursor=data.get("cursor"))
