"""Pure Square-to-CSV-column mapping: Catalog+Inventory to snapshot, Orders to sales.

The header tuples ARE the interface to the DIS mapping template: their column names are
``store_sku_current_position`` / ``store_sku_sale_events`` field keys, so the tenant's
template auto-maps them. This module is pure (no I/O, no vendor client); it takes parsed
Square JSON and returns ``ExtractRow`` values (all strings, the CSV cell shape). The
connector never calls ``dis-mapping``.

Follow-ups (tracked in connectors/BUILD.md section 10, not resolved here):
- ``tax_treatment`` is NOT NULL on both canonical models but has no direct Square source
  (denormalized-from-store in DIS). It is deliberately NOT emitted, so snapshot rows are
  INCOMPLETE and take the streaming consumer's conditional-update path until the product
  decision lands. Emitting an invented default would be an unilateral product decision.
- RETURN / VOID discrimination from Square refunds, and precise money semantics
  (tax/discount handling), are mapping refinements; v1 maps order line items as SALE and
  uses pre-tax amounts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from thalamus_connector_sdk import ExtractRow

# Target CSV columns = canonical field keys (a test guards them against the models).
SNAPSHOT_HEADER: tuple[str, ...] = (
    "sku_id",
    "product_name",
    "product_description",
    "product_category",
    "barcode",
    "current_retail_price",
    "currency",
    "stock_qty",
)
SALES_HEADER: tuple[str, ...] = (
    "sku_id",
    "event_subtype",
    "source_sale_timestamp",
    "transaction_id",
    "line_item_seq",
    "quantity",
    "unit_retail_price",
    "unit_sale_price",
    "currency",
    "payment_method",
)

# Currency minor-unit exponents (Square money `amount` is in the smallest unit).
_ZERO_DECIMAL = frozenset({"JPY", "KRW", "VND", "CLP", "ISK"})
_THREE_DECIMAL = frozenset({"BHD", "KWD", "OMR", "TND", "JOD"})


def _minor_unit_digits(currency: str) -> int:
    if currency in _ZERO_DECIMAL:
        return 0
    if currency in _THREE_DECIMAL:
        return 3
    return 2


def money_to_amount(amount_minor: int, currency: str) -> str:
    """A Square money amount (minor units) rendered as a decimal string in major units."""
    digits = _minor_unit_digits(currency)
    quantum = Decimal(10) ** digits
    return str((Decimal(amount_minor) / quantum).quantize(Decimal(1) / quantum if digits else Decimal(1)))


def _money_field(money: Mapping[str, Any] | None) -> tuple[str, str]:
    """(amount_string, currency) from a Square money object, or ("", "")."""
    if not money:
        return "", ""
    amount = money.get("amount")
    currency = money.get("currency") or ""
    if amount is None or not currency:
        return "", currency
    return money_to_amount(int(amount), currency), currency


def catalog_inventory_to_rows(
    items: Sequence[Mapping[str, Any]],
    *,
    categories: Mapping[str, str],
    inventory_by_variation: Mapping[str, str],
) -> tuple[list[ExtractRow], list[str]]:
    """Join Square Catalog ITEMs (with nested variations) and Inventory counts into
    ``store_sku_current_position`` rows, one per variation.

    A variation with no usable ``price_money`` is DROPPED (never emitted as a blank
    ``current_retail_price``, which would fail the hot NOT NULL and, with no per-row
    partial write downstream, withhold the whole chunk's good rows). Returns
    ``(rows, dropped_skus)`` where ``dropped_skus`` are the excluded ``sku_id``s for the
    connector's counted audit signal.
    """
    rows: list[ExtractRow] = []
    dropped: list[str] = []
    for item in items:
        item_data = item.get("item_data") or {}
        name = str(item_data.get("name") or "")
        description = item_data.get("description")
        category_id = item_data.get("category_id")
        category = categories.get(category_id) if isinstance(category_id, str) else None
        for variation in item_data.get("variations") or []:
            vdata = variation.get("item_variation_data") or {}
            variation_id = str(variation.get("id") or "")
            sku = str(vdata.get("sku") or variation_id)
            price, currency = _money_field(vdata.get("price_money"))
            if not price:
                dropped.append(sku)  # no usable price -> not mappable to current_retail_price
                continue
            values: dict[str, str] = {"sku_id": sku, "product_name": name, "current_retail_price": price}
            if currency:
                values["currency"] = currency
            if isinstance(description, str) and description:
                values["product_description"] = description
            if category:
                values["product_category"] = category
            upc = vdata.get("upc")
            if isinstance(upc, str) and upc:
                values["barcode"] = upc
            qty = inventory_by_variation.get(variation_id)
            if qty is not None:
                values["stock_qty"] = str(qty)
            rows.append(ExtractRow(values=values))
    return rows, dropped


def inventory_to_rows(inventory_by_variation: Mapping[str, str]) -> list[ExtractRow]:
    """Inventory-only refresh: sku_id + stock_qty rows (a partial snapshot). These are
    INCOMPLETE by design and take the consumer's conditional-update path (D63)."""
    return [
        ExtractRow(values={"sku_id": variation_id, "stock_qty": str(quantity)})
        for variation_id, quantity in inventory_by_variation.items()
    ]


def orders_to_rows(orders: Sequence[Mapping[str, Any]]) -> list[ExtractRow]:
    """Map Square Orders line items to ``store_sku_sale_events`` rows.

    ``source_event_id_hint`` is ``transaction_id:line_item_seq`` (D33/D65); the streaming
    consumer derives the canonical ``source_event_id`` from the mapped columns.
    """
    rows: list[ExtractRow] = []
    for order in orders:
        transaction_id = str(order.get("id") or "")
        timestamp = str(order.get("closed_at") or order.get("created_at") or "")
        tender_types = _tender_types(order)
        for seq, line_item in enumerate(order.get("line_items") or [], start=1):
            sku = str(line_item.get("catalog_object_id") or "")
            quantity = str(line_item.get("quantity") or "")
            retail, currency = _money_field(line_item.get("base_price_money"))
            # Pre-tax, post-discount line total gives the per-unit sale price and keeps
            # unit_sale_price <= unit_retail_price (the DB CHECK). With no line total the
            # sale price IS the retail price (no discount) - reuse the retail string so the
            # two columns stay format-consistent.
            sale_source = line_item.get("variation_total_price_money")
            sale_currency = ""
            if sale_source:
                sale_total, sale_currency = _money_field(sale_source)
                unit_sale = _per_unit(sale_total, quantity) if sale_total else retail
            else:
                unit_sale = retail
            values: dict[str, str] = {
                "sku_id": sku,
                "event_subtype": "SALE",
                "source_sale_timestamp": timestamp,
                "transaction_id": transaction_id,
                "line_item_seq": str(seq),
                "quantity": quantity,
            }
            if retail:
                values["unit_retail_price"] = retail
            if unit_sale:
                values["unit_sale_price"] = unit_sale
            currency_code = currency or sale_currency
            if currency_code:
                values["currency"] = currency_code
            if tender_types:
                values["payment_method"] = tender_types
            rows.append(ExtractRow(values=values, source_event_id_hint=f"{transaction_id}:{seq}"))
    return rows


def _per_unit(total_major: str, quantity: str) -> str:
    """Divide a major-unit total by the line quantity, or "" if not computable."""
    try:
        qty = Decimal(quantity)
        if qty == 0:
            return ""
        return str((Decimal(total_major) / qty).quantize(Decimal("0.0001")))
    except (ArithmeticError, ValueError):
        return ""


def _tender_types(order: Mapping[str, Any]) -> str:
    """A '+'-joined set of tender types on the order, for payment_method (or "")."""
    tenders = order.get("tenders") or []
    types = [str(tender.get("type")) for tender in tenders if tender.get("type")]
    return "+".join(dict.fromkeys(types))
