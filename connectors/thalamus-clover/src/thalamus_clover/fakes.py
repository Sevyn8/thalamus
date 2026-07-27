"""Offline fakes for the Clover connector: canned catalog, no network.

``FakeCloverApi`` satisfies the ``CloverApi`` Protocol with fixed items / categories /
stocks, so the spine runs a real pull with zero Clover account or network.
``FakeSessionStore`` yields a dummy session. Both are dev/offline artifacts; the real
``CloverPuller`` + ``CloverTokenStore`` remain the production path.

The canned data deliberately covers BOTH stock branches, because the untracked branch is
production truth rather than a sandbox gap: two items are tracked (one of them at a
genuine zero) and two are not.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from thalamus_clover.puller import ItemPage
from thalamus_clover_oauth import CloverSession

_MERCHANT_ID = "0RKKDBMKPAH71"

_CANNED_CATEGORIES: dict[str, dict[str, Any]] = {
    "CAT_GROCERY": {"id": "CAT_GROCERY", "name": "Grocery", "sortOrder": 2},
    "CAT_STATIONARY": {"id": "CAT_STATIONARY", "name": "Stationary", "sortOrder": 1},
}

_CANNED_ITEMS: list[dict[str, Any]] = [
    {
        "id": "ITEM_MANGO",
        "name": "Mango",
        "price": 10000,
        "priceType": "FIXED",
        "categories": {"elements": [{"id": "CAT_GROCERY"}]},
    },
    {
        # Carries a merchant SKU, so sku_source is merchant_sku for this one.
        "id": "ITEM_PENCIL",
        "name": "Pencil",
        "sku": "STAT-PENCIL-01",
        "price": 100,
        "priceType": "FIXED",
        "categories": {"elements": [{"id": "CAT_STATIONARY"}]},
    },
    {
        # price 0 is a VALUE, not an absence: it is emitted.
        "id": "ITEM_NOODLES",
        "name": "Noodles",
        "price": 0,
        "priceType": "FIXED",
        "categories": {"elements": []},
    },
    {
        # Two categories: the (sortOrder, id) rule must pick Stationary (sortOrder 1).
        "id": "ITEM_GIFTSET",
        "name": "Gift Set",
        "price": 2500,
        "priceType": "FIXED",
        "categories": {"elements": [{"id": "CAT_GROCERY"}, {"id": "CAT_STATIONARY"}]},
    },
    {
        # Not a retail price: dropped and counted.
        "id": "ITEM_LOOSETEA",
        "name": "Loose Tea",
        "price": 300,
        "priceType": "PER_UNIT",
        "categories": {"elements": []},
    },
]

# Only two items are tracked. ITEM_MANGO is a genuine zero (emits "0"); ITEM_NOODLES and
# ITEM_GIFTSET are untracked and must omit stock_qty entirely.
_CANNED_STOCKS: dict[str, str] = {"ITEM_MANGO": "0", "ITEM_PENCIL": "42"}


class FakeSessionStore:
    """A dev session store: any tenant/source resolves to a dummy token + test merchant."""

    def get_session(self, tenant_id: UUID, source_id: str) -> CloverSession:
        return CloverSession(access_token="fake-sandbox-token", merchant_id=_MERCHANT_ID)


class FakeCloverApi:
    """Canned Clover API (offline). Snapshot pull uses merchant + items + categories + stocks."""

    def rate_limit_state(self) -> str | None:
        """Never throttled: the fake serves canned data and makes no vendor call."""
        return None

    def get_merchant(self, token: str, merchant_id: str) -> dict[str, Any]:
        return {
            "id": merchant_id,
            "name": "Test Merchant",
            "properties": {"defaultCurrency": "USD"},
        }

    def list_items(self, token: str, merchant_id: str, cursor: str | None) -> ItemPage:
        # One page, then done: a short page ends the collection (no continuation token).
        return ItemPage(items=list(_CANNED_ITEMS), next_cursor=None)

    def list_categories(self, token: str, merchant_id: str) -> dict[str, dict[str, Any]]:
        return dict(_CANNED_CATEGORIES)

    def list_item_stocks(self, token: str, merchant_id: str) -> dict[str, str]:
        return dict(_CANNED_STOCKS)
