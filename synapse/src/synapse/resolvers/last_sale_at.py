"""The ``last_sale_at`` resolver: the most recent SALE per (tenant, store, sku).

No new canonical table, no new collapse logic, no new grain rule, no probe: it reuses
``_collapse.collapse_latest_wins`` unchanged and obeys the same predicate-placement rule as
``daily_series``.

DO NOT "OPTIMISE" THIS AWAY INTO current_state. THE TRAP, NAMED.
================================================================

``current_state`` already returns ``last_source_event_at``, which looks exactly like the field
this capability computes, and reaching for it would make this module look redundant. It is not
the same field and substituting it silently under-reports dead stock.

Canonical's own comment on that column: "Source event timestamp of the last event-table row
merged into this hot row." BOTH event tables feed that merge — the streaming consumer's
normalize step branches on ``is_sale`` and produces a hot contribution either way, and the hot
merge takes the later event time. So ``last_source_event_at`` is bumped by:

  - a sale                       (movement — what dead stock cares about)
  - a RETURN or a VOID           (not movement, and arguably the opposite)
  - a price change               (no movement at all)
  - an inventory adjustment      (no movement at all)
  - a catalogue attribute edit   (no movement at all)

A SKU with no sales for two hundred days and a repricing yesterday therefore has a
``last_source_event_at`` of yesterday, and a dead-stock rule built on it reports that SKU as
freshly moved. The failure is silent, in the permissive direction, and it looks like the
catalogue is healthier than it is — which is the direction nobody investigates.

SALE ONLY, AND RETURN/VOID ARE EXCLUDED ON PURPOSE. A return is stock ARRIVING, not leaving; a
void is a sale that did not happen. Neither is evidence that a SKU moves. This is a different
subtype treatment from ``daily_series``, which sums all three into ``net_quantity`` because a
net daily movement legitimately includes returns — two capabilities over one table, treating
the vocabulary differently, each declaring what it did in its ``returns``.

The subtype filter goes OUTSIDE the collapse: ``event_subtype`` is not a dedup-key column, so a
correction can change it, and filtering inside would let a superseded row survive as the
"latest". Same rule, same reason, as ``sku_id`` and the date window in ``daily_series``.

READ-ONLY, ALWAYS. No INSERT/UPDATE/DELETE is constructed anywhere in this module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Final
from uuid import UUID

from sqlalchemy import ColumnElement, and_, column, func, select, table
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_canonical import StoreSkuSaleEvent
from dis_rls import rls_session
from synapse.core.capability import CapabilityScope
from synapse.core.errors import ResultTooLargeError
from synapse.core.last_sale_at import LastSaleAtRow
from synapse.resolvers._collapse import collapse_latest_wins

# The ONE place this capability names a canonical table — the SAME table daily_series reads,
# which is why no new containment surface appears. The column list is DERIVED from the
# canonical model so the construct cannot drift from dis-canonical.
_CANONICAL_SCHEMA = "canonical"
_SALE_EVENTS_TABLE = "store_sku_sale_events"
_EVENT_TIME_COLUMN = "source_sale_timestamp"

_COLUMNS: tuple[str, ...] = tuple(StoreSkuSaleEvent.model_fields)

_sale_events = table(
    _SALE_EVENTS_TABLE,
    *(column(name) for name in _COLUMNS),
    schema=_CANONICAL_SCHEMA,
)

# The grain this capability returns, which is also its declared descriptor grain. No date
# column: this is a READING, not a series, so there is no grain rule to satisfy here — the rule
# applies to probes, and this capability declares no gates.
_GRAIN: Final[tuple[str, ...]] = ("tenant_id", "store_id", "sku_id")

# The subtype that counts as movement. A tuple of one, so widening it is a visible edit rather
# than a changed comparison — and a unit test pins it against canonical's CHECK vocabulary so
# that a new subtype cannot arrive without someone deciding whether it is movement.
_MOVEMENT_SUBTYPES: Final[tuple[str, ...]] = ("SALE",)

_AGGREGATE_COLUMNS: Final[tuple[str, ...]] = (
    "tenant_id",
    "store_id",
    "sku_id",
    "event_date",
    "event_subtype",
)

# RAISES rather than clamps, for the same reason daily_series does and a stronger one.
# current_state clamps because a caller can see it got exactly the limit; here a MISSING ROW
# MEANS "NEVER SOLD" to the only consumer this has, so a truncated result does not read as
# partial — it reads as a catalogue full of dead stock. That is a wrong answer, not a short one.
#
# One row per position, so the same order as current_state: fine at beta (66 positions), and
# 125,000 at the beta TARGET of 5,000 SKUs x 25 stores, which exceeds this. Keyset
# pagination is the answer then, not a bigger number.
_MAX_ROWS = 20_000


def _check_aggregate_columns() -> None:
    """Fail loudly at import if a column this resolver names is gone from the canonical model."""
    missing = [name for name in _AGGREGATE_COLUMNS if name not in _COLUMNS]
    if missing:
        raise ValueError(
            f"canonical.{_SALE_EVENTS_TABLE} no longer carries {missing}, which last_sale_at "
            "aggregates over. This must fail at import, not return a plausible answer built "
            "from whatever remains"
        )


_check_aggregate_columns()


def _key_scoped_predicate(scope: CapabilityScope, store_id: UUID | None) -> ColumnElement[bool]:
    """The predicate safe to push INSIDE the collapse: dedup-key components only.

    The in-query tenant predicate is redundant with RLS by design, exactly as DIS's own
    tenant-facing reads are: RLS is the floor, the predicate is the statement of intent, and the
    two agreeing is what stops a future RLS-off table from silently becoming a fleet read.
    """
    clauses: list[ColumnElement[bool]] = [_sale_events.c.tenant_id == scope.tenant_id]
    if store_id is not None:
        clauses.append(_sale_events.c.store_id == store_id)
    return and_(*clauses)


def _project(mapping: Mapping[str, object]) -> LastSaleAtRow:
    """Project one aggregate row into the capability's return shape."""
    return LastSaleAtRow(
        tenant_id=UUID(str(mapping["tenant_id"])),
        store_id=UUID(str(mapping["store_id"])),
        sku_id=str(mapping["sku_id"]),
        last_sale_date=_as_date(mapping["last_sale_date"]),
    )


def _as_date(value: object) -> date:
    """A DATE, and specifically not a datetime.

    ``datetime`` subclasses ``date``, so a plain isinstance check would let a timestamp through
    and the row would silently describe an instant where the contract promises a UTC day. Also
    never None: MAX over a non-empty group of a NOT NULL column cannot be NULL, so a None here
    means the query is not the query this function thinks it is.
    """
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValueError(
            f"last_sale_date came back as {type(value).__name__}, expected a plain date; "
            "MAX(event_date) over a non-empty group cannot be NULL"
        )
    return value


async def resolve_last_sale_at(
    engine: AsyncEngine,
    scope: CapabilityScope,
    *,
    store_id: UUID | None = None,
    sku_id: str | None = None,
    limit: int = _MAX_ROWS,
) -> Sequence[LastSaleAtRow]:
    """The most recent SALE date per (tenant, store, sku), corrections collapsed at read time.

    ``scope`` carries the tenant and is the ONLY source of tenancy — never a caller field,
    never defaulted. ``store_id`` and ``sku_id`` narrow within it and cannot widen it.

    NO DATE WINDOW, and that is not an omission. "When did this last sell" is a question about
    all of history: a window would turn "last sold 400 days ago" into "no row", which the only
    consumer reads as "never sold" — a different and stronger claim. The cost is a collapse over
    the tenant's whole sale history, which is the honest price of the question.

    Positions with NO sales are ABSENT from the result. See the module docstring: that absence
    is the dead-stock signal, read against ``current_state``'s universe.

    Raises ``ResultTooLargeError`` rather than truncating (see ``_MAX_ROWS``), ``ValueError`` if
    canonical's shape has moved, and whatever ``dis_rls`` raises for a wrong database or a
    bypassing role.
    """
    if limit < 1 or limit > _MAX_ROWS:
        limit = _MAX_ROWS

    collapsed = collapse_latest_wins(
        _sale_events,
        event_time_column=_EVENT_TIME_COLUMN,
        where=_key_scoped_predicate(scope, store_id),
    )

    # OUTSIDE the collapse, on the SURVIVING rows: neither event_subtype nor sku_id is a
    # dedup-key component, so a correction can change either.
    survivor_filters: list[ColumnElement[bool]] = [
        collapsed.c.event_subtype.in_(_MOVEMENT_SUBTYPES),
    ]
    if sku_id is not None:
        survivor_filters.append(collapsed.c.sku_id == sku_id)

    group_columns = tuple(collapsed.c[name] for name in _GRAIN)
    statement = (
        select(*group_columns, func.max(collapsed.c.event_date).label("last_sale_date"))
        .where(and_(*survivor_filters))
        .group_by(*group_columns)
        .order_by(collapsed.c.store_id, collapsed.c.sku_id)
        # One over the limit, so exceeding it is DETECTED rather than silently delivered as
        # exactly-the-limit rows.
        .limit(limit + 1)
    )

    async with rls_session(engine, scope.tenant_id) as conn:
        rows = (await conn.execute(statement)).mappings().all()

    if len(rows) > limit:
        raise ResultTooLargeError(
            f"last_sale_at produced more than {limit} positions for tenant {scope.tenant_id} "
            f"(store_id={store_id}, sku_id={sku_id}); narrow the store or the SKU — the result "
            "was NOT truncated, because a missing row here means 'never sold'"
        )
    return [_project(dict(row)) for row in rows]


__all__ = ["resolve_last_sale_at"]
