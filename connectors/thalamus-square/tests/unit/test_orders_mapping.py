"""Orders to the sale-event path, with the source_event_id hint.

The header is guarded against StoreSkuSaleEvent; the per-row hint is
``transaction_id:line_item_seq``; unit_sale_price stays <= unit_retail_price (the DB CHECK).
"""

from __future__ import annotations

from decimal import Decimal

from dis_canonical import StoreSkuSaleEvent
from thalamus_square.mapping import SALES_HEADER, orders_to_rows

_ORDERS = [
    {
        "id": "ORDER_1",
        "location_id": "LOC_1",
        "created_at": "2026-07-18T10:00:00Z",
        "closed_at": "2026-07-18T10:05:00Z",
        "tenders": [{"type": "CARD"}],
        "line_items": [
            {
                "uid": "li-1",
                "catalog_object_id": "VAR_1",
                "quantity": "2",
                "base_price_money": {"amount": 1000, "currency": "USD"},
                "variation_total_price_money": {"amount": 1800, "currency": "USD"},
            },
            {
                "uid": "li-2",
                "catalog_object_id": "VAR_2",
                "quantity": "1",
                "base_price_money": {"amount": 500, "currency": "USD"},
            },
        ],
    }
]


def test_sales_header_is_canonical_field_keys() -> None:
    assert set(SALES_HEADER) <= set(StoreSkuSaleEvent.model_fields)


def test_order_line_items_become_sale_rows_with_hints() -> None:
    rows = orders_to_rows(_ORDERS)
    assert len(rows) == 2

    first = rows[0]
    assert first.values["sku_id"] == "VAR_1"
    assert first.values["event_subtype"] == "SALE"
    assert first.values["source_sale_timestamp"] == "2026-07-18T10:05:00Z"  # closed_at wins
    assert first.values["transaction_id"] == "ORDER_1"
    assert first.values["line_item_seq"] == "1"
    assert first.values["quantity"] == "2"
    assert first.values["unit_retail_price"] == "10.00"
    assert first.values["unit_sale_price"] == "9.0000"  # 18.00 / 2
    assert first.values["currency"] == "USD"
    assert first.values["payment_method"] == "CARD"
    assert first.source_event_id_hint == "ORDER_1:1"

    assert rows[1].source_event_id_hint == "ORDER_1:2"
    assert rows[1].values["unit_sale_price"] == rows[1].values["unit_retail_price"]  # no discount


def test_unit_sale_price_never_exceeds_retail() -> None:
    for row in orders_to_rows(_ORDERS):
        retail = Decimal(row.values["unit_retail_price"])
        sale = Decimal(row.values["unit_sale_price"])
        assert sale <= retail
