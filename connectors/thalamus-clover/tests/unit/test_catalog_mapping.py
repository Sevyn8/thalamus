"""Pure Clover-to-CSV mapping: the stock rule, category determinism, price, sku provenance.

Offline: no client, no network. Every rule here was a decision with a stated rationale, so
each has a test that would fail if someone "simplified" it back.
"""

from __future__ import annotations

from typing import Any

from thalamus_clover.mapping import (
    SKU_SOURCE_CLOVER_ID,
    SKU_SOURCE_MERCHANT,
    SNAPSHOT_HEADER,
    STOCK_SUPPRESSED_NEGATIVE,
    STOCK_SUPPRESSED_UNPARSEABLE,
    first_category_name,
    items_to_rows,
    price_to_amount,
    stock_suppression_reason,
)

_CATS: dict[str, dict[str, Any]] = {
    "CAT_G": {"id": "CAT_G", "name": "Grocery", "sortOrder": 2},
    "CAT_S": {"id": "CAT_S", "name": "Stationary", "sortOrder": 1},
}


def _item(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "ITEM_1",
        "name": "Mango",
        "price": 10000,
        "priceType": "FIXED",
        "categories": {"elements": []},
    }
    base.update(over)
    return base


def _rows(items: list[dict[str, Any]], stock: dict[str, str] | None = None) -> list[dict[str, str]]:
    rows, _, _ = items_to_rows(items, categories=_CATS, stock_by_item=stock or {}, currency="USD")
    return [r.values for r in rows]


# -- stock: the NULL-vs-0 rule, both branches ----------------------------------------


def test_tracked_item_emits_its_quantity() -> None:
    assert _rows([_item()], {"ITEM_1": "42"})[0]["stock_qty"] == "42"


def test_a_genuine_zero_emits_zero() -> None:
    # Counted and found empty: that IS a stock level and must be recorded.
    assert _rows([_item()], {"ITEM_1": "0"})[0]["stock_qty"] == "0"


def test_the_three_stock_branches_together() -> None:
    """Negative -> NULL, zero -> "0", untracked -> no key. ONE test on purpose.

    The three only make sense against each other, and each is a decision someone could
    plausibly "simplify" in isolation: clamping the negative to 0, treating the zero as
    absent, or defaulting the untracked to 0. Keeping them in one test means collapsing any
    one of them fails here with all three in view.
    """
    rows = _rows(
        [_item(id="NEG"), _item(id="ZERO"), _item(id="UNTRACKED")],
        {"NEG": "-3", "ZERO": "0"},  # UNTRACKED deliberately absent from the stock map
    )
    by_id = {v["sku_id"]: v for v in rows}

    # NEGATIVE: withheld. Clover permits overselling; canonical's
    # ck_sscp_stock_qty_non_negative does not, so passing it through would die at the
    # canonical boundary far from its cause. NULL means "not known", nearer the truth than
    # zero, which would assert "none in stock" when the truth is "oversold".
    assert "stock_qty" not in by_id["NEG"]
    assert by_id["NEG"].get("stock_qty") not in ("0", "-3")

    # ZERO: counted and found empty. That IS a stock level and must survive.
    assert by_id["ZERO"]["stock_qty"] == "0"

    # UNTRACKED: never counted. Write-presence semantics keep attribute_freshness honest.
    assert "stock_qty" not in by_id["UNTRACKED"]

    # All three rows are still EMITTED: a suppressed field is not a dropped row.
    assert len(rows) == 3


def test_a_suppressed_quantity_is_reported_separately_from_dropped_rows() -> None:
    # dropped_count reconciles against bronze.row_count ("difference points to quarantined
    # rows"), so a field suppression must never inflate it.
    rows, dropped, suppressed = items_to_rows(
        [_item(id="NEG"), _item(id="OK"), _item(id="VAR", priceType="VARIABLE")],
        categories=_CATS,
        stock_by_item={"NEG": "-1", "OK": "5"},
        currency="USD",
    )
    assert suppressed.negative == ["NEG"]
    assert suppressed.unparseable == []
    assert dropped == ["VAR"]  # the row-drop counter is untouched by the suppression
    assert {r.values["sku_id"] for r in rows} == {"NEG", "OK"}


def test_the_two_suppression_causes_are_reported_separately() -> None:
    # A negative is valid merchant behaviour; an unparseable quantity means Clover's wire
    # contract changed. If they shared a bucket, a vendor schema break would hide inside a
    # crowd of ordinary oversells and surface weeks later as "all our stock went null".
    rows, _, suppressed = items_to_rows(
        [_item(id="NEG"), _item(id="JUNK")],
        categories=_CATS,
        stock_by_item={"NEG": "-1", "JUNK": "n/a"},
        currency="USD",
    )
    assert suppressed.negative == ["NEG"]
    assert suppressed.unparseable == ["JUNK"]
    assert all("stock_qty" not in r.values for r in rows)  # both withheld
    assert len(rows) == 2  # both rows still emitted


def test_suppression_reasons_are_distinct_tokens() -> None:
    assert stock_suppression_reason("-1") == STOCK_SUPPRESSED_NEGATIVE
    assert stock_suppression_reason("n/a") == STOCK_SUPPRESSED_UNPARSEABLE
    assert STOCK_SUPPRESSED_NEGATIVE != STOCK_SUPPRESSED_UNPARSEABLE


def test_fractional_and_boundary_quantities_pass_through_verbatim() -> None:
    # stock_qty is NUMERIC(14,3); Clover reports fractional counts, and the vendor string
    # is carried as-is rather than reformatted.
    assert stock_suppression_reason("0.0") is None
    assert stock_suppression_reason("12.500") is None
    assert stock_suppression_reason("-0.001") == STOCK_SUPPRESSED_NEGATIVE
    # and the emitted cell is the vendor string verbatim, not a reformatted Decimal
    assert _rows([_item(id="F")], {"F": "12.500"})[0]["stock_qty"] == "12.500"


def test_tracked_and_untracked_items_coexist_in_one_page() -> None:
    values = _rows([_item(id="A"), _item(id="B")], {"A": "7"})
    by_id = {v["sku_id"]: v for v in values}
    assert by_id["A"]["stock_qty"] == "7"
    assert "stock_qty" not in by_id["B"]


# -- product_category: determinism ----------------------------------------------------


def test_category_picks_lowest_sort_order() -> None:
    item = _item(categories={"elements": [{"id": "CAT_G"}, {"id": "CAT_S"}]})
    assert _rows([item])[0]["product_category"] == "Stationary"  # sortOrder 1 beats 2


def test_category_pick_is_order_independent() -> None:
    # The whole point of the rule: the same unchanged catalog must not produce different
    # canonical rows run to run, which downstream would read as phantom change events.
    forward = _item(categories={"elements": [{"id": "CAT_G"}, {"id": "CAT_S"}]})
    reverse = _item(categories={"elements": [{"id": "CAT_S"}, {"id": "CAT_G"}]})
    assert _rows([forward])[0]["product_category"] == _rows([reverse])[0]["product_category"]


def test_equal_sort_order_ties_break_on_id() -> None:
    cats = {
        "CAT_B": {"id": "CAT_B", "name": "Bravo", "sortOrder": 1},
        "CAT_A": {"id": "CAT_A", "name": "Alpha", "sortOrder": 1},
    }
    refs = [{"id": "CAT_B"}, {"id": "CAT_A"}]
    assert first_category_name(refs, categories=cats) == "Alpha"  # id CAT_A < CAT_B


def test_uncategorised_item_omits_the_column() -> None:
    assert "product_category" not in _rows([_item()])[0]


def test_an_unknown_category_id_does_not_crash_the_run() -> None:
    # A category deleted between the two calls must not fail the pull; it sorts last.
    item = _item(categories={"elements": [{"id": "CAT_GONE"}, {"id": "CAT_S"}]})
    assert _rows([item])[0]["product_category"] == "Stationary"


# -- price ----------------------------------------------------------------------------


def test_price_converts_minor_to_major_units() -> None:
    assert price_to_amount(10000, "USD") == "100.00"
    assert price_to_amount(500, "USD") == "5.00"
    assert price_to_amount(500, "JPY") == "500"  # zero-decimal currency


def test_price_zero_is_emitted_not_dropped() -> None:
    # Clover reports it PRESENT with priceType FIXED, so it is a value, not an absence.
    # A suspicious zero belongs to Data Quality downstream, not the connector's judgement.
    values = _rows([_item(price=0)])[0]
    assert values["current_retail_price"] == "0.00"
    assert values["currency"] == "USD"


def test_non_fixed_price_type_is_dropped_and_counted() -> None:
    # VARIABLE / PER_UNIT price at the till, so the value is not a retail price; emitting
    # it into current_retail_price would be WRONG, not merely incomplete.
    rows, dropped, _ = items_to_rows(
        [_item(id="KEEP"), _item(id="DROP", priceType="PER_UNIT"), _item(id="VAR", priceType="VARIABLE")],
        categories=_CATS,
        stock_by_item={},
        currency="USD",
    )
    assert [r.values["sku_id"] for r in rows] == ["KEEP"]
    assert dropped == ["DROP", "VAR"]


# -- sku provenance --------------------------------------------------------------------


def test_merchant_sku_is_used_and_labelled() -> None:
    values = _rows([_item(sku="STAT-01")])[0]
    assert values["sku_id"] == "STAT-01"
    assert values["sku_source"] == SKU_SOURCE_MERCHANT


def test_missing_sku_falls_back_to_the_clover_id_visibly() -> None:
    # The fallback is right, but it must not be silent: a vendor object id must be
    # distinguishable from a merchant-assigned SKU.
    values = _rows([_item(id="ITEM_X")])[0]
    assert values["sku_id"] == "ITEM_X"
    assert values["sku_source"] == SKU_SOURCE_CLOVER_ID


def test_empty_string_sku_is_treated_as_absent() -> None:
    assert _rows([_item(sku="")])[0]["sku_source"] == SKU_SOURCE_CLOVER_ID


# -- header ----------------------------------------------------------------------------


def test_header_is_clovers_own_and_omits_what_clover_lacks() -> None:
    # D1: Clover defines its own header. Description does not exist on Clover items and no
    # barcode was ever observed, so neither is carried.
    assert "product_description" not in SNAPSHOT_HEADER
    assert "barcode" not in SNAPSHOT_HEADER
    assert SNAPSHOT_HEADER == (
        "sku_id",
        "sku_source",
        "product_name",
        "product_category",
        "current_retail_price",
        "currency",
        "stock_qty",
    )


def test_every_emitted_key_is_in_the_header() -> None:
    # The header IS the CSV column set; a value key outside it would be silently dropped
    # by the serializer.
    rows, _, _ = items_to_rows(
        [_item(sku="S1", categories={"elements": [{"id": "CAT_S"}]})],
        categories=_CATS,
        stock_by_item={"ITEM_1": "3"},
        currency="USD",
    )
    assert set(rows[0].values) <= set(SNAPSHOT_HEADER)
