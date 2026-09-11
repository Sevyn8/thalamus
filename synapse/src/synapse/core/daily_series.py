"""The ``daily_series`` projection — what the capability RETURNS.

PURE, like its ``current_state`` sibling and enforced the same way: import-linter forbids
dis_canonical, dis_rls and sqlalchemy to ``synapse.core``, so the aggregate SQL and the
canonical row shapes stay one layer up in ``synapse.resolvers.daily_series``.

ONE ROW IS ONE (tenant, store, sku, UTC DAY), AFTER THE READ-TIME COLLAPSE. What that means
precisely, because a daily quantity that is quietly double-counted is worse than no
daily quantity at all:

- Redeliveries do not appear. Migration 0019's unique index suppresses byte-identical
  repeats at write time, and the read-time collapse removes any that predate it.
- A CORRECTION under the same dedup key appears ONCE, as the corrected value.
- A correction from a source with no transaction id does NOT collapse: its
  fallback dedup key embeds the bronze object it arrived in, so the original and the
  correction are different keys and BOTH are counted. This is a real limitation of the
  key, not of the query, and the resolver's docstring carries it in full.

``net_quantity`` IS SIGNED AND IS NOT "SALES". RETURN and VOID rows carry negative
quantity by CHECK constraint and their own dedup keys, so they are summed in. The three
line counts are what let a consumer see the composition instead of inferring it from a
sign.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class DailySeriesRow:
    """Net movement for one SKU at one store on one UTC day.

    Grain is (tenant_id, store_id, sku_id, event_date) — declared on the capability
    descriptor so a consumer can join without guessing, and matching this dataclass
    field-for-field (a unit test pins the two together).
    """

    tenant_id: UUID
    store_id: UUID
    sku_id: str
    # UTC DAY, not a local business day. The canonical sale-events table derives
    # event_date from source_sale_timestamp at UTC under a CHECK constraint, so an
    # evening sale in IST can land on the following UTC date. A store-local series is a
    # different capability (it needs the store timezone, which Synapse does not read
    # today), not a flag here.
    event_date: date
    # Decimal, never float: canonical stores quantity as NUMERIC(14,3) and a daily sum
    # is a figure someone reconciles against a POS report.
    net_quantity: Decimal
    sale_line_count: int
    return_line_count: int
    void_line_count: int


__all__ = ["DailySeriesRow"]
