"""Pure Clover-to-CSV-column mapping: Items + Categories + ItemStocks to a snapshot.

CLOVER DEFINES ITS OWN HEADER (D1). It deliberately does NOT conform to
``thalamus_square.mapping.SNAPSHOT_HEADER``, and the difference is not laziness: Clover
items carry no description at all, and no barcode was ever observed on the wire. The
mapping-template layer is where vendor differences are absorbed, so the connector emits
what the vendor actually has. Extracting a shared header at two vendors would be a guess;
at three it would be evidence.

This module is pure (no I/O, no vendor client): it takes parsed Clover JSON and returns
``ExtractRow`` values (all strings, the CSV cell shape). The connector never calls
``dis-mapping``.

--- stock_qty: OMITTED when untracked, never 0 -------------------------------------------

Clover inventory tracking is OPT-IN PER ITEM and many real merchants never enable it, so an
absent stock level is production truth, not a sandbox gap. An untracked item therefore
carries NO ``stock_qty`` key at all; only a genuinely counted zero emits ``"0"``.

Three reasons, strongest last:

1. Zero means "none in stock"; absent means "nobody counts this". Emitting 0 would fire
   every stock-out alarm downstream for items nobody tracks.
2. ``canonical.store_sku_current_position.stock_qty`` is ``NUMERIC(14,3) NULL`` with
   ``CHECK (stock_qty IS NULL OR stock_qty >= 0)``, so an untracked item lands cleanly as
   NULL.
3. ``attribute_freshness`` is WRITE-PRESENCE semantics - a column never carried has no key.
   Omitting keeps the freshness map honest; emitting 0 would stamp "we knew the stock at T"
   for an item nobody counted. This is the decisive argument and it is invisible from the
   connector side, which is why it is written here.

--- product_category: first by (sortOrder, id) --------------------------------------------

A Clover item can carry 0..n categories. We take sortOrder ascending, tie-break on id, and
use the first. The argument is DETERMINISM, not information preservation: a non-deterministic
pick makes the same unchanged catalog produce different canonical rows run to run, which
surfaces downstream as phantom change events. A ``+``-joined string was rejected because it
is a synthetic value no mapping template can match. The discarded categories are simply
dropped - no machinery preserves them.

--- sku_id / sku_source -------------------------------------------------------------------

Clover items may carry a merchant-assigned ``sku``; none of the sandbox items do. Falling
back to the Clover object id is right, but a SILENT fallback would make a vendor id
indistinguishable from a real SKU. ``sku_source`` records which per row.

``sku_source`` is a BRONZE-ONLY provenance column with no canonical counterpart - do not go
looking for it in Canonical Explorer. It is safe to leave unmapped: ``dis_mapping``'s rename
stage selects only the columns the mapping declares and drops the rest ("extra source
columns are the source's business", D18), so an unmapped source column is never an error.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from thalamus_connector_sdk import ExtractRow

# Clover's snapshot columns. Named as canonical field keys where a canonical column exists,
# so a tenant's template auto-maps them; `sku_source` is the one bronze-only extra.
SNAPSHOT_HEADER: tuple[str, ...] = (
    "sku_id",
    "sku_source",
    "product_name",
    "product_category",
    "current_retail_price",
    "currency",
    "stock_qty",
)

# `sku_source` values: which identifier `sku_id` actually carries, per row.
SKU_SOURCE_MERCHANT = "merchant_sku"
SKU_SOURCE_CLOVER_ID = "clover_item_id"

# Only a FIXED price is a retail price. VARIABLE / PER_UNIT items price at the till, so
# their `price` is not a retail price and emitting it into current_retail_price would be
# WRONG rather than merely incomplete - they are dropped and counted (Square's
# drop-and-count precedent, correctly applied).
PRICE_TYPE_FIXED = "FIXED"

# Currency minor-unit exponents (Clover `price` is in the smallest unit of the merchant's
# defaultCurrency, exactly as Square's money amounts are).
_ZERO_DECIMAL = frozenset({"JPY", "KRW", "VND", "CLP", "ISK"})
_THREE_DECIMAL = frozenset({"BHD", "KWD", "OMR", "TND", "JOD"})


def _minor_unit_digits(currency: str) -> int:
    if currency in _ZERO_DECIMAL:
        return 0
    if currency in _THREE_DECIMAL:
        return 3
    return 2


def price_to_amount(price_minor: int, currency: str) -> str:
    """A Clover price (minor units) rendered as a decimal string in major units."""
    digits = _minor_unit_digits(currency)
    quantum = Decimal(10) ** digits
    return str((Decimal(price_minor) / quantum).quantize(Decimal(1) / quantum if digits else Decimal(1)))


def first_category_name(
    category_refs: Sequence[Mapping[str, Any]], *, categories: Mapping[str, Mapping[str, Any]]
) -> str:
    """The item's category name, picked deterministically by (sortOrder, id).

    ``category_refs`` are the item's expanded ``categories.elements`` (which carry ids);
    ``categories`` is the merchant's category collection keyed by id, which is where
    ``sortOrder`` authoritatively lives. A ref whose id is unknown to the collection sorts
    last rather than crashing - a category deleted between the two calls must not fail a run.
    """
    resolved: list[tuple[int, str, str]] = []
    for ref in category_refs:
        category_id = ref.get("id")
        if not isinstance(category_id, str):
            continue
        record = categories.get(category_id)
        # An unknown id sorts last; a missing sortOrder sorts last within its id.
        order = record.get("sortOrder") if record else None
        name = str((record or {}).get("name") or ref.get("name") or "")
        resolved.append((int(order) if isinstance(order, int) else 2**31, category_id, name))
    if not resolved:
        return ""
    resolved.sort(key=lambda entry: (entry[0], entry[1]))
    return resolved[0][2]


def items_to_rows(
    items: Sequence[Mapping[str, Any]],
    *,
    categories: Mapping[str, Mapping[str, Any]],
    stock_by_item: Mapping[str, str],
    currency: str,
) -> tuple[list[ExtractRow], list[str]]:
    """Join Clover Items, Categories and ItemStocks into snapshot rows, one per item.

    Returns ``(rows, dropped_ids)``; ``dropped_ids`` are the items excluded for a
    non-FIXED price, for the connector's counted audit signal.
    """
    rows: list[ExtractRow] = []
    dropped: list[str] = []
    for item in items:
        item_id = str(item.get("id") or "")
        if not item_id:
            continue
        price_type = str(item.get("priceType") or PRICE_TYPE_FIXED)
        if price_type != PRICE_TYPE_FIXED:
            dropped.append(item_id)  # not a retail price; see PRICE_TYPE_FIXED
            continue

        sku = item.get("sku")
        if isinstance(sku, str) and sku:
            sku_id, sku_source = sku, SKU_SOURCE_MERCHANT
        else:
            sku_id, sku_source = item_id, SKU_SOURCE_CLOVER_ID

        values: dict[str, str] = {
            "sku_id": sku_id,
            "sku_source": sku_source,
            "product_name": str(item.get("name") or ""),
        }

        # price 0 is a VALUE, not an absence: Clover reports it present with priceType
        # FIXED. Faithful extraction emits it; a suspicious zero belongs to Data Quality
        # and Needs Attention downstream, not to the connector's judgement.
        price = item.get("price")
        if isinstance(price, int):
            values["current_retail_price"] = price_to_amount(price, currency)
            if currency:
                values["currency"] = currency

        category_refs = (item.get("categories") or {}).get("elements") or []
        category = first_category_name(category_refs, categories=categories)
        if category:
            values["product_category"] = category

        # THE stock rule (see the module docstring): present-and-counted emits, including
        # "0"; untracked omits the key entirely so the cell is blank -> NULL downstream.
        quantity = stock_by_item.get(item_id)
        if quantity is not None:
            values["stock_qty"] = quantity

        rows.append(ExtractRow(values=values))
    return rows, dropped
