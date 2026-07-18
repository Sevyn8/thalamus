"""SquareAdapter extract/authenticate over a fake Square API (no network).

Proves the adapter satisfies the ConnectorAdapter contract: authenticate resolves the
token and locations, extract routes each Domain to the right table shape, and preflight
reuses the SDK structural verdict.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from thalamus_connector_sdk import AuthContext, Domain, ExtractResult, ExtractRow
from thalamus_connector_sdk.trigger import ConnectorTrigger
from thalamus_square.adapter import SquareAdapter
from thalamus_square.mapping import SALES_HEADER, SNAPSHOT_HEADER
from thalamus_square.puller import CatalogPage, OrdersPage

_TENANT = UUID("019e5e3c-b5d3-705f-9002-2451c4ca2626")
_STORE = UUID("019e5e3c-b5d3-705f-9002-2451c4ca2700")
_TRACE = UUID("019e8d88-4e76-7911-bb77-d8fcba1808a6")
_TEMPLATE = UUID("019e93f0-57ca-7470-9899-ba6532ff1600")


def _trigger(domain: Domain) -> ConnectorTrigger:
    return ConnectorTrigger(
        schema_version=1,
        trace_id=_TRACE,
        connector_run_id="run_square_0001",
        tenant_id=_TENANT,
        store_id=_STORE,
        source_id="square_pos",
        template_id=_TEMPLATE,
        domains=[domain],
        cursor=None,
    )


class _FakeTokenStore:
    def get_token(self, tenant_id: UUID) -> str:
        return "sandbox-token"


class _FakeApi:
    def list_locations(self, token: str) -> list[dict[str, Any]]:
        return [{"id": "LOC_1", "name": "Flagship"}]

    def list_catalog(self, token: str, cursor: str | None) -> CatalogPage:
        return CatalogPage(
            items=[
                {
                    "type": "ITEM",
                    "id": "ITEM_1",
                    "item_data": {
                        "name": "Widget",
                        "category_id": "CAT_1",
                        "variations": [
                            {
                                "id": "VAR_1",
                                "item_variation_data": {
                                    "sku": "SKU-1",
                                    "price_money": {"amount": 999, "currency": "USD"},
                                },
                            }
                        ],
                    },
                }
            ],
            categories={"CAT_1": "Hardware"},
            next_cursor="cat-cursor-2",
        )

    def batch_inventory(
        self, token: str, *, catalog_object_ids: Sequence[str], location_ids: Sequence[str]
    ) -> dict[str, str]:
        assert "VAR_1" in catalog_object_ids
        return {"VAR_1": "7"}

    def search_orders(self, token: str, *, location_ids: Sequence[str], cursor: str | None) -> OrdersPage:
        return OrdersPage(
            orders=[
                {
                    "id": "ORDER_1",
                    "created_at": "2026-07-18T10:00:00Z",
                    "line_items": [
                        {
                            "catalog_object_id": "VAR_1",
                            "quantity": "1",
                            "base_price_money": {"amount": 999, "currency": "USD"},
                        }
                    ],
                }
            ],
            next_cursor="ord-cursor-2",
        )


def _adapter() -> SquareAdapter:
    return SquareAdapter(api=_FakeApi(), token_store=_FakeTokenStore())


def test_authenticate_resolves_token_and_locations() -> None:
    auth = _adapter().authenticate(_trigger(Domain.CATALOG))
    assert auth.token == "sandbox-token"
    assert auth.extra["location_ids"] == ["LOC_1"]
    assert auth.store_by_code == {"LOC_1": "Flagship"}


def test_extract_catalog_produces_snapshot_rows() -> None:
    adapter = _adapter()
    auth = adapter.authenticate(_trigger(Domain.CATALOG))
    result = adapter.extract(auth, Domain.CATALOG, None)
    assert result.header == SNAPSHOT_HEADER
    assert result.next_cursor == "cat-cursor-2"
    assert result.rows[0].values["sku_id"] == "SKU-1"
    assert result.rows[0].values["stock_qty"] == "7"


def test_extract_orders_produces_sale_rows_with_hint() -> None:
    adapter = _adapter()
    auth = adapter.authenticate(_trigger(Domain.ORDERS))
    result = adapter.extract(auth, Domain.ORDERS, None)
    assert result.header == SALES_HEADER
    assert result.next_cursor == "ord-cursor-2"
    assert result.rows[0].source_event_id_hint == "ORDER_1:1"


def test_extract_inventory_is_partial_snapshot() -> None:
    adapter = _adapter()
    auth = adapter.authenticate(_trigger(Domain.INVENTORY))
    result = adapter.extract(auth, Domain.INVENTORY, None)
    assert result.header == ("sku_id", "stock_qty")
    assert result.rows[0].values == {"sku_id": "VAR_1", "stock_qty": "7"}


class _FakeApiPriceless(_FakeApi):
    def batch_inventory(
        self, token: str, *, catalog_object_ids: Sequence[str], location_ids: Sequence[str]
    ) -> dict[str, str]:
        return {}  # no inventory needed for the drop test

    def list_catalog(self, token: str, cursor: str | None) -> CatalogPage:
        return CatalogPage(
            items=[
                {
                    "type": "ITEM",
                    "id": "ITEM_1",
                    "item_data": {
                        "name": "Widget",
                        "variations": [
                            {
                                "id": "VAR_P",
                                "item_variation_data": {
                                    "sku": "SKU-P",
                                    "price_money": {"amount": 500, "currency": "USD"},
                                },
                            },
                            {"id": "VAR_N", "item_variation_data": {"sku": "SKU-N"}},  # no price
                        ],
                    },
                }
            ],
            categories={},
            next_cursor=None,
        )


def test_extract_catalog_reports_dropped_priceless() -> None:
    adapter = SquareAdapter(api=_FakeApiPriceless(), token_store=_FakeTokenStore())
    auth = adapter.authenticate(_trigger(Domain.CATALOG))
    result = adapter.extract(auth, Domain.CATALOG, None)
    assert result.dropped_count == 1
    assert "SKU-N" in result.dropped_sample
    assert {row.values["sku_id"] for row in result.rows} == {"SKU-P"}


def test_preflight_flags_empty_extract() -> None:
    empty = ExtractResult(domain=Domain.CATALOG, header=SNAPSHOT_HEADER, rows=(), next_cursor=None)
    assert not _adapter().preflight(empty).ok


def test_adapter_satisfies_protocol_shape() -> None:
    # A light structural check: the fake wiring returns the SDK types.
    auth = _adapter().authenticate(_trigger(Domain.CATALOG))
    assert isinstance(auth, AuthContext)
    result = _adapter().extract(auth, Domain.CATALOG, None)
    assert isinstance(result.rows[0], ExtractRow)
