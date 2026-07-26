"""Offline fakes for the Square connector: canned catalog+inventory, no network.

``FakeSquareApi`` satisfies the ``SquareApi`` Protocol with fixed catalog + inventory data
(a Żabka W-001 snapshot), so the spine runs a real pull with zero Square account or network.
``FakeTokenStore`` yields a dummy token. Both are dev/offline artifacts; the real
``SquarePuller`` + ``EnvTokenStore`` remain the production path.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from thalamus_square.puller import CatalogPage, OrdersPage

_LOCATION: dict[str, Any] = {"id": "LOC_WAW", "name": "Zabka W-001 Mokotow"}

# Two catalog ITEMs, each with one priced variation (PLN). Enough to land two snapshot rows.
_CANNED_ITEMS: list[dict[str, Any]] = [
    {
        "type": "ITEM",
        "id": "ITEM_COFFEE",
        "item_data": {
            "name": "Zabka Coffee 250g",
            "description": "Ground coffee",
            "category_id": "CAT_BEV",
            "variations": [
                {
                    "id": "VAR_COFFEE",
                    "item_variation_data": {
                        "sku": "ZAB-COFFEE-250",
                        "upc": "5900000000001",
                        "price_money": {"amount": 1299, "currency": "PLN"},
                    },
                }
            ],
        },
    },
    {
        "type": "ITEM",
        "id": "ITEM_CHIPS",
        "item_data": {
            "name": "Zabka Chips 100g",
            "description": "Salted potato chips",
            "category_id": "CAT_SNK",
            "variations": [
                {
                    "id": "VAR_CHIPS",
                    "item_variation_data": {
                        "sku": "ZAB-CHIPS-100",
                        "upc": "5900000000002",
                        "price_money": {"amount": 499, "currency": "PLN"},
                    },
                }
            ],
        },
    },
]
_CANNED_CATEGORIES: dict[str, str] = {"CAT_BEV": "Beverages", "CAT_SNK": "Snacks"}
_CANNED_INVENTORY: dict[str, str] = {"VAR_COFFEE": "37", "VAR_CHIPS": "12"}


class FakeTokenStore:
    """A dev token store: any tenant/source resolves to a dummy sandbox token."""

    def get_token(self, tenant_id: UUID, source_id: str) -> str:
        return "fake-sandbox-token"


class FakeSquareApi:
    """Canned Square API (offline). Snapshot pull uses locations + catalog + inventory."""

    def list_locations(self, token: str) -> list[dict[str, Any]]:
        return [_LOCATION]

    def list_catalog(self, token: str, cursor: str | None) -> CatalogPage:
        return CatalogPage(items=list(_CANNED_ITEMS), categories=dict(_CANNED_CATEGORIES), next_cursor=None)

    def batch_inventory(
        self, token: str, *, catalog_object_ids: Sequence[str], location_ids: Sequence[str]
    ) -> dict[str, str]:
        return dict(_CANNED_INVENTORY)

    def search_orders(self, token: str, *, location_ids: Sequence[str], cursor: str | None) -> OrdersPage:
        return OrdersPage(orders=[], next_cursor=None)
