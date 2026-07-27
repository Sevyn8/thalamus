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

--- stock_qty: a NEGATIVE quantity is also suppressed to NULL -------------------------------

Clover's merchant setting "Allow negative stock counts" is a normal production
configuration, so an oversold item genuinely reports a quantity below zero. Canonical
refuses it: ``ck_sscp_stock_qty_non_negative`` is
``CHECK (stock_qty IS NULL OR stock_qty >= 0)``. Passing the negative through would land in
bronze and then die at the canonical boundary - failing far from its cause, in a service
that has no idea Clover permits overselling.

So a negative emits NO ``stock_qty`` key. NOT the negative value, and NOT clamped to 0:
NULL already means "not known", which is nearer the truth than zero, whereas zero would
assert "none in stock" when the truth is "oversold".

The suppression is NOT counted into ``dropped_count``. That counter is for DROPPED ROWS
(the non-FIXED price case below is the precedent), and the pipeline forwards it into health
metadata and the RECEIVED audit, where it reconciles against ``bronze.row_count`` -
"streaming consumer reports rows processed; difference points to quarantined rows", per the
bronze DDL. A negative quantity suppresses one FIELD while the row is still emitted. Row
dropped and field suppressed are different events and must not share a counter.

An UNPARSEABLE quantity is withheld the same way but is NOT the same event, and the two are
reported under separate reason tokens (see :data:`STOCK_SUPPRESSED_NEGATIVE` /
:data:`STOCK_SUPPRESSED_UNPARSEABLE`). A negative is valid merchant behaviour; an
unparseable one means Clover's wire contract changed.

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
from dataclasses import dataclass, field
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


# Why a stock quantity was withheld. TWO tokens, not one, because the causes are
# different in kind and must stay greppable apart:
#
#   NEGATIVE     - VALID Clover data we cannot store. The merchant setting "Allow negative
#                  stock counts" is on and an item is oversold. Merchant behaviour; expected
#                  in production; interesting only in aggregate.
#   UNPARSEABLE  - Clover's WIRE CONTRACT CHANGED. A quantity that is not a number means the
#                  field's type or shape moved under us. A vendor schema break, and urgent.
#
# Collapsing these into one message would make the day Clover changes that field's type read
# as a busy day of overselling, and we would find out weeks later as "all our stock went null".
STOCK_SUPPRESSED_NEGATIVE = "negative_quantity"
STOCK_SUPPRESSED_UNPARSEABLE = "unparseable_quantity"


@dataclass(frozen=True)
class StockSuppressions:
    """Item ids whose ``stock_qty`` was withheld, SPLIT BY CAUSE (see the tokens above).

    Deliberately not one flat list: the adapter logs the two separately so a vendor schema
    break can never hide inside a crowd of ordinary oversells.
    """

    negative: list[str] = field(default_factory=list)
    unparseable: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.negative or self.unparseable)


def stock_suppression_reason(raw: str) -> str | None:
    """The reason ``raw`` cannot be emitted as ``stock_qty``, or None when it can.

    Zero passes through - it is a real count. When None is returned the caller emits the
    vendor string VERBATIM rather than a reformatted Decimal, so the CSV carries what Clover
    said, exactly as the price path does.
    """
    try:
        quantity = Decimal(raw)
    except (ArithmeticError, ValueError):
        return STOCK_SUPPRESSED_UNPARSEABLE
    return STOCK_SUPPRESSED_NEGATIVE if quantity < 0 else None


def items_to_rows(
    items: Sequence[Mapping[str, Any]],
    *,
    categories: Mapping[str, Mapping[str, Any]],
    stock_by_item: Mapping[str, str],
    currency: str,
) -> tuple[list[ExtractRow], list[str], StockSuppressions]:
    """Join Clover Items, Categories and ItemStocks into snapshot rows, one per item.

    Returns ``(rows, dropped_ids, stock_suppressed_ids)``:

    - ``dropped_ids`` are items EXCLUDED from ``rows`` for a non-FIXED price. These feed
      ``ExtractResult.dropped_count``, which reconciles against ``bronze.row_count``.
    - ``suppressions`` are items STILL EMITTED whose quantity was withheld, split by cause.
      Deliberately SEPARATE from ``dropped_ids``: a suppressed field is not a dropped row,
      and conflating them would corrupt that reconciliation. The adapter logs these; nothing
      counts them into the row arithmetic.
    """
    rows: list[ExtractRow] = []
    dropped: list[str] = []
    suppressions = StockSuppressions()
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

        # THE stock rule (see the module docstring). Three outcomes, all of which keep the
        # row: counted emits (including "0"); untracked omits the key; negative/unparseable
        # omits the key AND is recorded, BY CAUSE, for the adapter to log.
        quantity = stock_by_item.get(item_id)
        if quantity is not None:
            reason = stock_suppression_reason(quantity)
            if reason is None:
                values["stock_qty"] = quantity
            elif reason == STOCK_SUPPRESSED_NEGATIVE:
                suppressions.negative.append(item_id)
            else:
                suppressions.unparseable.append(item_id)

        rows.append(ExtractRow(values=values))
    return rows, dropped, suppressions
