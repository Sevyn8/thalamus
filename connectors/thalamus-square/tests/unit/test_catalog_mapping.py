"""Catalog + Inventory to store_sku_current_position CSV columns.

The header IS the mapping-template interface, so it must be canonical field keys (guarded
against the live model). Money is converted from Square minor units to major-unit decimals.
"""

from __future__ import annotations

from dis_canonical import StoreSkuCurrentPosition
from dis_enrichment import CURRENT_POSITION, enrichment_fields
from dis_validation import mandatory_mapping_produced
from thalamus_square.mapping import (
    SNAPSHOT_HEADER,
    catalog_inventory_to_rows,
    money_to_amount,
)

_ITEMS = [
    {
        "type": "ITEM",
        "id": "ITEM_1",
        "item_data": {
            "name": "Widget",
            "description": "A widget",
            "category_id": "CAT_1",
            "variations": [
                {
                    "type": "ITEM_VARIATION",
                    "id": "VAR_1",
                    "item_variation_data": {
                        "sku": "SKU-1",
                        "upc": "0123456789012",
                        "price_money": {"amount": 999, "currency": "USD"},
                    },
                }
            ],
        },
    }
]
_CATEGORIES = {"CAT_1": "Hardware"}
_INVENTORY = {"VAR_1": "42"}


def test_snapshot_header_is_canonical_field_keys() -> None:
    # Drift guard: every emitted column must be a real StoreSkuCurrentPosition field so the
    # snapshot template auto-maps it (no stray/non-canonical columns).
    assert set(SNAPSHOT_HEADER) <= set(StoreSkuCurrentPosition.model_fields)


def test_snapshot_header_covers_the_hot_completeness_required_set() -> None:
    # Recompute the consumer's completeness gate set from the SAME derivation
    # (streaming-consumer/pipeline/mapping.py HOT_REQUIRED_FROM_PROJECTION) and assert the
    # Square snapshot header covers it. A future migration that adds a mandatory
    # mapping-produced hot column fails HERE, telling us to add it to the header.
    required = mandatory_mapping_produced(
        StoreSkuCurrentPosition,
        enrichment_guaranteed=frozenset(enrichment_fields(CURRENT_POSITION)),
    )
    assert required <= set(SNAPSHOT_HEADER), f"header missing: {required - set(SNAPSHOT_HEADER)}"
    assert required == {"sku_id", "product_name", "current_retail_price"}  # pin today's set


def test_catalog_inventory_join_produces_snapshot_row() -> None:
    rows, dropped = catalog_inventory_to_rows(
        _ITEMS, categories=_CATEGORIES, inventory_by_variation=_INVENTORY
    )
    assert dropped == []
    assert len(rows) == 1
    values = rows[0].values
    assert values["sku_id"] == "SKU-1"
    assert values["product_name"] == "Widget"
    assert values["product_description"] == "A widget"
    assert values["product_category"] == "Hardware"
    assert values["barcode"] == "0123456789012"
    assert values["current_retail_price"] == "9.99"
    assert values["currency"] == "USD"
    assert values["stock_qty"] == "42"
    assert rows[0].source_event_id_hint is None  # snapshot rows carry no event hint


def test_variation_without_inventory_omits_stock() -> None:
    rows, _dropped = catalog_inventory_to_rows(_ITEMS, categories={}, inventory_by_variation={})
    assert "stock_qty" not in rows[0].values
    assert "product_category" not in rows[0].values  # no category map entry


def test_priceless_variation_is_dropped_and_reported() -> None:
    # A variation with no price_money must NOT emit a blank current_retail_price; it is
    # dropped and its sku_id returned for the connector's counted audit signal.
    items = [
        {
            "type": "ITEM",
            "id": "ITEM_2",
            "item_data": {
                "name": "No-Price Widget",
                "variations": [
                    {"id": "VAR_2", "item_variation_data": {"sku": "SKU-2"}},  # no price_money
                ],
            },
        }
    ]
    rows, dropped = catalog_inventory_to_rows(items, categories={}, inventory_by_variation={})
    assert rows == []
    assert dropped == ["SKU-2"]


def test_money_conversion_respects_minor_units() -> None:
    assert money_to_amount(999, "USD") == "9.99"
    assert money_to_amount(1000, "JPY") == "1000"  # zero-decimal currency
    assert money_to_amount(1234567, "BHD") == "1234.567"  # three-decimal currency
