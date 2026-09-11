"""The ``daily_series`` resolver, and the probe that measures its precondition.

Resolution here answers "can this be satisfied FOR THIS TENANT, RIGHT NOW", not merely
"does a resolver exist". Two structural facts:

1. GATES. The capability declares the KIND it can be measured on
   (``synapse.core.capability.GateKind``), a caller supplies the threshold and the policy
   (``synapse.core.analysis``), and the MEASUREMENT is here — ``probe_min_history_days`` names
   a table, so it can only live in this package. That three-way split is the whole reason
   the resolution outcomes can be told apart without running the resolver body. The
   measurement grain is ``SERIES_GRAIN``, and the registry checks it against the descriptor's
   declared grain at import; see that constant for the per-tenant defect it exists to prevent.
   Thresholds live on the caller's declaration, not the descriptor: two callers may want
   different numbers.
2. The read-time correction collapse as a shared helper (``._collapse``). An aggregate over
   the raw event table double-counts every correction — ``SUM(quantity) GROUP BY date`` is
   exactly the case that exposes it.

WHERE EACH PREDICATE GOES, AND WHY IT IS NOT A PERFORMANCE QUESTION. This is the
subtlest thing in the module:

- ``tenant_id`` and ``store_id`` are pushed INSIDE the collapse. Safe because both are
  components of the dedup key: a correction cannot change them and remain the same
  logical event, so restricting to them cannot hide a superseding row.
- ``sku_id`` and the DATE WINDOW are applied OUTSIDE the collapse, to the surviving rows.
  They are NOT in the dedup key, so a correction may change either — a mis-mapped SKU
  fixed, or a sale timestamp corrected across a month boundary. Filtered inside, the
  collapse would only see the original, declare it the survivor, and return a value that
  had already been superseded. Correct totals cost a collapse over the store's history;
  a cheap wrong answer is not the trade this capability is allowed to make.

WHAT THIS RESOLVER CANNOT PROMISE, stated because the sibling ``current_state`` promises
more and the difference is easy to assume away: current_state validates every row through
``StoreSkuCurrentPosition`` with ``extra='forbid'``, so an ADDED canonical column fails
loudly on the first row. An aggregate returns no canonical row to validate, so that half
of the property is gone here. What survives is the removal direction, and it survives
because the column list is DERIVED from ``StoreSkuSaleEvent.model_fields`` and the
collapse helper raises on a missing key column: a canonical drop or rename fails at
statement build or at execute, not silently. The addition direction is not detectable
from an aggregate, and no amount of care here changes that.

READ-ONLY, ALWAYS. No INSERT/UPDATE/DELETE is constructed anywhere in this module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Final, get_args
from uuid import UUID

from sqlalchemy import ColumnElement, Select, and_, column, func, select, table, tuple_
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_canonical import StoreSkuSaleEvent
from dis_canonical.shared import SaleEventSubtype
from dis_rls import rls_session
from synapse.core.capability import CapabilityScope
from synapse.core.daily_series import DailySeriesRow
from synapse.core.errors import ResultTooLargeError
from synapse.core.resolution import Observation
from synapse.resolvers._collapse import collapse_latest_wins

# The ONE place this capability names a canonical table. The column list is DERIVED from
# the canonical model rather than typed out, so the construct cannot drift from
# dis-canonical: a field added or removed there changes this table's columns with it.
_CANONICAL_SCHEMA = "canonical"
_SALE_EVENTS_TABLE = "store_sku_sale_events"

# The event-time column for THIS table. store_sku_change_events uses
# source_event_timestamp; the collapse helper takes it as a parameter for exactly that
# reason, mirroring the streaming consumer's own per-model mapping.
_EVENT_TIME_COLUMN = "source_sale_timestamp"

_COLUMNS: tuple[str, ...] = tuple(StoreSkuSaleEvent.model_fields)

# THE GRAIN THE PRECONDITION IS MEASURED AT, declared as data so it can be CHECKED rather
# than trusted. It is the capability's declared grain minus the date column, and
# `_check_registry` asserts exactly that at import — the rule being that a precondition must
# be measured at the grain the capability's rows are AT.
#
# WHY THIS EXISTS AS A CONSTANT. A probe that counts COUNT(DISTINCT event_date) per TENANT
# passes a 60-day threshold trivially on a tenant with 613 events spread over 66 (store, sku)
# pairs at roughly 9 observations each — a number that describes the tenant's calendar and
# nothing about whether any series is forecastable. When the measured grain is buried in a
# WHERE clause, nothing can see it disagree with the declared grain. As a tuple, two layers
# can compare them.
#
# tenant_id is included even though the WHERE clause pins it, so that this tuple IS the
# query's GROUP BY rather than something derived from it. Grouping by a constant column costs
# nothing and removes the derivation the guard would otherwise have to replicate.
SERIES_GRAIN: Final[tuple[str, ...]] = ("tenant_id", "store_id", "sku_id")

# The grain column that makes this capability a SERIES rather than a reading. Excluded from
# SERIES_GRAIN because coverage is a count OF dates: putting it in the group would make every
# group one date and every coverage 1.
DATE_COLUMN: Final[str] = "event_date"

_sale_events = table(
    _SALE_EVENTS_TABLE,
    *(column(name) for name in _COLUMNS),
    schema=_CANONICAL_SCHEMA,
)

# One count per subtype in canonical's CHECK vocabulary
# (ck_ssse_event_subtype_vocab), keyed by the subtype and mapped to the projection field
# it populates. NOT derived from the Literal by string munging: the field names are real
# fields on DailySeriesRow and must be stated, so that widening the vocabulary upstream
# cannot silently add an uncounted subtype.
_SUBTYPE_COUNTS: Final[Mapping[str, str]] = {
    "SALE": "sale_line_count",
    "RETURN": "return_line_count",
    "VOID": "void_line_count",
}

# The columns the aggregate itself names, beyond what the collapse helper checks. Verified
# against the applied DDL; the check below is what makes a canonical drop loud rather than
# a confusing AttributeError deep inside statement construction.
_AGGREGATE_COLUMNS: Final[tuple[str, ...]] = (
    "tenant_id",
    "store_id",
    "sku_id",
    "event_date",
    "quantity",
    "event_subtype",
)

# A runaway guard, and — unlike current_state's — it RAISES rather than clamps. See
# ResultTooLargeError: this grain multiplies stores by SKUs by DAYS, and a clamped series
# is missing DATES, which reads as "no sales that day" rather than as truncation. At beta
# SKU counts one store-month exceeds this, so a caller wanting that narrows by SKU; the
# answer when a real consumer needs more is keyset pagination, not a bigger number.
_MAX_ROWS = 20_000

# The most qualifying series a fetch will narrow BY IDENTITY. The narrowing renders as a tuple
# IN-list, so it is linear in the population; 5,000 keys is already a large statement and a
# tenant past it needs the predicate pushed into SQL as a coverage HAVING clause instead of a
# key list. Raising rather than truncating: a silently shortened IN-list would exclude series
# that DID qualify, which is the same class of wrongness the narrowing exists to prevent.
_MAX_SERIES = 5_000


def _check_subtype_coverage() -> None:
    """Fail loudly if canonical's subtype vocabulary and the counted set disagree.

    Called at import. The vocabulary is a CHECK constraint in the DDL and a ``Literal`` in
    dis-canonical, so widening it is a migration plus a model edit — and this resolver
    would otherwise keep returning three counts that no longer add up to the rows summed
    into ``net_quantity``. A silent gap between a total and its composition is the kind of
    thing nobody notices for two quarters.
    """
    declared = set(get_args(SaleEventSubtype))
    counted = set(_SUBTYPE_COUNTS)
    if declared != counted:
        raise ValueError(
            "canonical's sale-event subtype vocabulary and daily_series's counted set "
            f"disagree: declared={sorted(declared)}, counted={sorted(counted)}. "
            "Widening the vocabulary requires a new count column on DailySeriesRow and "
            "a new entry in the descriptor's `returns`"
        )


def _check_aggregate_columns() -> None:
    """Fail loudly if a column the aggregate names is gone from the canonical model."""
    missing = [name for name in _AGGREGATE_COLUMNS if name not in _COLUMNS]
    if missing:
        raise ValueError(
            f"canonical.{_SALE_EVENTS_TABLE} no longer carries {missing}, which "
            "daily_series aggregates over. This must fail at import, not return a "
            "plausible series built from whatever remains"
        )


_check_subtype_coverage()
_check_aggregate_columns()


def _key_scoped_predicate(scope: CapabilityScope, store_id: UUID | None) -> ColumnElement[bool]:
    """The predicate safe to push INSIDE the collapse: dedup-key components only.

    The in-query tenant predicate is redundant with RLS by design, exactly as DIS's own
    tenant-facing reads are and as ``current_state`` is: RLS is the floor, the predicate
    is the statement of intent, and the two agreeing is what stops a future RLS-off table
    from silently becoming a fleet read.
    """
    clauses: list[ColumnElement[bool]] = [_sale_events.c.tenant_id == scope.tenant_id]
    if store_id is not None:
        clauses.append(_sale_events.c.store_id == store_id)
    return and_(*clauses)


def _project(mapping: Mapping[str, object]) -> DailySeriesRow:
    """Project one aggregate row into the capability's return shape.

    ``net_quantity`` cannot legitimately be NULL: every group holds at least one row and
    ``quantity`` is NOT NULL in canonical, so a NULL sum means the query is not the query
    this function thinks it is. Loud, not coalesced to zero — a zero would be
    indistinguishable from a real day of offsetting returns.
    """
    net_quantity = mapping["net_quantity"]
    if not isinstance(net_quantity, Decimal):
        raise ValueError(
            f"net_quantity came back as {type(net_quantity).__name__}, expected Decimal "
            "over NUMERIC(14,3); SUM returned NULL or the driver changed types"
        )
    return DailySeriesRow(
        tenant_id=UUID(str(mapping["tenant_id"])),
        store_id=UUID(str(mapping["store_id"])),
        sku_id=str(mapping["sku_id"]),
        event_date=_as_date(mapping["event_date"]),
        net_quantity=net_quantity,
        sale_line_count=int(str(mapping["sale_line_count"])),
        return_line_count=int(str(mapping["return_line_count"])),
        void_line_count=int(str(mapping["void_line_count"])),
    )


def _as_date(value: object) -> date:
    """A DATE, and specifically not a datetime.

    ``datetime`` subclasses ``date`` in Python, so a plain ``isinstance`` check would let a
    timestamp through and the grain would quietly stop being a day — every row a distinct
    "day", and a series that looks like it has thousands of dates. The explicit rejection is
    the point of this function existing at all.
    """
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValueError(f"event_date came back as {type(value).__name__}, expected a plain date")
    return value


async def resolve_daily_series(
    engine: AsyncEngine,
    scope: CapabilityScope,
    *,
    date_from: date,
    date_to: date,
    store_id: UUID | None = None,
    sku_id: str | None = None,
    only_series: tuple[tuple[str, ...], ...] | None = None,
    limit: int = _MAX_ROWS,
) -> Sequence[DailySeriesRow]:
    """Net daily movement per SKU per store, corrections collapsed at read time.

    ``scope`` carries the tenant and is the ONLY source of tenancy — never a caller field,
    never defaulted. ``store_id`` narrows within it and cannot widen it: the RLS session is
    opened on the scope's tenant.

    ``date_from``/``date_to`` are REQUIRED and inclusive, both UTC dates. No default
    window exists on purpose: an AS_OF_DATE capability with an implicit "all history" is
    the series equivalent of a resolver that defaults to a cross-tenant read, and this
    grain multiplies stores by SKUs by days.

    WHAT THE COLLAPSE DOES AND DOES NOT REMOVE. Redeliveries: gone (suppressed at write by
    migration 0019, and any that predate it collapse here). Corrections under the same
    dedup key: counted ONCE, at the corrected value. Corrections from a source that
    supplies no ``transaction_id``/``line_item_seq``: **NOT collapsed** — the fallback
    dedup key embeds the bronze object, so the original and the correction are different keys and
    both are counted. That is a limitation of the key, not of this query, and a consumer
    reconciling against a POS report for such a source will see the difference.

    Raises ``ResultTooLargeError`` if the window and scope produce more than ``limit``
    groups — the series is not truncated, because a series with missing dates does not look
    truncated. Raises ``ValueError`` if canonical's shape has moved, and whatever
    ``dis_rls`` raises if the engine points at the wrong database or a bypassing role.
    """
    if date_from > date_to:
        raise ValueError(f"date_from {date_from} is after date_to {date_to}")
    if limit < 1 or limit > _MAX_ROWS:
        limit = _MAX_ROWS

    collapsed = collapse_latest_wins(
        _sale_events,
        event_time_column=_EVENT_TIME_COLUMN,
        where=_key_scoped_predicate(scope, store_id),
    )

    # OUTSIDE the collapse, on the SURVIVING rows: sku_id and event_date are not dedup-key
    # components, so a correction may move either. See the module docstring.
    survivor_filters: list[ColumnElement[bool]] = [
        collapsed.c.event_date >= date_from,
        collapsed.c.event_date <= date_to,
    ]
    if sku_id is not None:
        survivor_filters.append(collapsed.c.sku_id == sku_id)

    # THE QUALIFYING-POPULATION NARROWING. ``resolve()`` supplies this from the
    # probe's identities so the rows returned describe exactly the series the gate passed.
    #
    # None means UNMEASURED — no gate ran — and returns everything in scope. An EMPTY tuple is
    # refused rather than treated as "narrow to nothing": a caller that computed an empty
    # population and passed it here would otherwise get zero rows and no error, which is the
    # silent-nothing failure the whole change exists to prevent. Satisfied refuses to hold one
    # for the same reason; this is the second place it cannot happen.
    if only_series is not None:
        if not only_series:
            raise ValueError(
                "only_series is empty. Pass None for 'no narrowing'; an empty population would "
                "silently return zero rows while looking like a successful fetch"
            )
        if len(only_series) > _MAX_SERIES:
            raise ResultTooLargeError(
                f"only_series carries {len(only_series)} keys, more than the {_MAX_SERIES} this "
                "resolver will render as an IN-list"
            )
        # OUTSIDE the collapse, on surviving rows: sku_id is not a dedup-key component, so a
        # correction may move it — the same reason the sku_id filter above sits here.
        survivor_filters.append(
            tuple_(*(collapsed.c[name] for name in SERIES_GRAIN)).in_([tuple(key) for key in only_series])
        )

    group_columns = (
        collapsed.c.tenant_id,
        collapsed.c.store_id,
        collapsed.c.sku_id,
        collapsed.c.event_date,
    )
    statement = (
        select(
            *group_columns,
            func.sum(collapsed.c.quantity).label("net_quantity"),
            *(
                func.count().filter(collapsed.c.event_subtype == subtype).label(field)
                for subtype, field in _SUBTYPE_COUNTS.items()
            ),
        )
        .where(and_(*survivor_filters))
        .group_by(*group_columns)
        .order_by(collapsed.c.store_id, collapsed.c.sku_id, collapsed.c.event_date)
        # One over the limit, so exceeding it is DETECTED rather than silently delivered
        # as exactly-the-limit rows.
        .limit(limit + 1)
    )

    async with rls_session(engine, scope.tenant_id) as conn:
        rows = (await conn.execute(statement)).mappings().all()

    if len(rows) > limit:
        raise ResultTooLargeError(
            f"daily_series produced more than {limit} groups for tenant {scope.tenant_id} "
            f"over {date_from}..{date_to} (store_id={store_id}, sku_id={sku_id}); narrow "
            "the window, the store or the SKU — the series was NOT truncated"
        )
    return [_project(dict(row)) for row in rows]


def probe_statement(
    scope: CapabilityScope,
    *,
    store_id: UUID | None,
    sku_id: str | None,
    required: int,
) -> Select[tuple[int, int, datetime]]:
    """Build the coverage measurement. Pure — separated from execution so it is inspectable.

    A unit test compiles this and asserts the GROUP BY is exactly ``SERIES_GRAIN``, which is
    what stops the declared measurement grain from drifting away from the query that
    implements it. That drift is exactly how a declared grain and a measured grain come apart
    unnoticed.

    Shape:

        SELECT COUNT(*), COUNT(*) FILTER (WHERE coverage >= :required), now()
        FROM (SELECT <SERIES_GRAIN>, COUNT(DISTINCT event_date) AS coverage
              FROM <collapsed sale events>
              GROUP BY <SERIES_GRAIN>) per_series

    ``required`` is applied in SQL rather than in Python so the two counts come back as two
    integers instead of one row per series — a 5,000-SKU × 25-store tenant is 125,000 series,
    and shipping that to the client to filter it would be a distribution nobody asked for.
    The value is HANDED IN by the resolution engine from the descriptor; this module never
    sources a threshold.

    THE COLLAPSE IS APPLIED, and it is not optional here. "COUNT(DISTINCT event_date) is
    duplicate-insensitive" is true only of a per-TENANT count. At series grain it is
    false: a correction that
    changes ``sku_id`` files its dates under BOTH the old and the new SKU, inventing a
    phantom series and inflating a real one. Both errors are in the PERMISSIVE direction —
    more series, higher coverage — which is the wrong direction for a gate. The cost is a
    sort over rows this query already scans.

    ``sku_id`` is filtered OUTSIDE the collapse and ``store_id`` inside, for the same reason
    as in ``resolve_daily_series``: only dedup-key components are safe inside.
    """
    collapsed = collapse_latest_wins(
        _sale_events,
        event_time_column=_EVENT_TIME_COLUMN,
        where=_key_scoped_predicate(scope, store_id),
    )
    per_series_columns = [collapsed.c[name] for name in SERIES_GRAIN]
    per_series = select(
        *per_series_columns,
        func.count(func.distinct(collapsed.c[DATE_COLUMN])).label("coverage"),
    )
    if sku_id is not None:
        per_series = per_series.where(collapsed.c.sku_id == sku_id)
    per_series_subquery = per_series.group_by(*per_series_columns).subquery("per_series")

    return select(
        func.count().label("pairs_measured"),
        func.count().filter(per_series_subquery.c.coverage >= required).label("pairs_qualifying"),
        func.now().label("measured_at"),
    ).select_from(per_series_subquery)


def qualifying_statement(
    scope: CapabilityScope,
    *,
    store_id: UUID | None = None,
    sku_id: str | None = None,
    required: int,
) -> Select[tuple[str, str, str]]:
    """WHICH series clear ``required``, at SERIES_GRAIN. The identities behind the counts.

    The counts alone cannot narrow a fetch, so without this an analysis under ANY_SERIES
    would receive rows for series the gate had just refused.

    DELIBERATELY A SEPARATE STATEMENT rather than a widened ``probe_statement``. The counts are
    an aggregate over the per-series subquery and the identities are the subquery's rows; one
    statement returning both would either repeat the subquery or return the counts on every row.
    Two statements in ONE transaction (see ``probe_min_history_days``) keeps them describing the
    same instant, which is the only property that matters.

    The predicate is IDENTICAL to probe_statement's, built the same way from the same helpers,
    so the two cannot drift into measuring different populations.
    """
    collapsed = collapse_latest_wins(
        _sale_events,
        event_time_column=_EVENT_TIME_COLUMN,
        where=_key_scoped_predicate(scope, store_id),
    )
    per_series_columns = [collapsed.c[name] for name in SERIES_GRAIN]
    per_series = select(
        *per_series_columns,
        func.count(func.distinct(collapsed.c[DATE_COLUMN])).label("coverage"),
    )
    if sku_id is not None:
        per_series = per_series.where(collapsed.c.sku_id == sku_id)
    per_series_subquery = per_series.group_by(*per_series_columns).subquery("per_series")

    return (
        select(*(per_series_subquery.c[name] for name in SERIES_GRAIN))
        .where(per_series_subquery.c.coverage >= required)
        .order_by(*(per_series_subquery.c[name] for name in SERIES_GRAIN))
        # One over the cap, so exceeding it is DETECTED rather than silently truncated into a
        # narrowing that would exclude qualifying series without saying so.
        .limit(_MAX_SERIES + 1)
    )


async def probe_min_history_days(
    engine: AsyncEngine,
    scope: CapabilityScope,
    *,
    store_id: UUID | None = None,
    sku_id: str | None = None,
    required: int,
) -> Observation:
    """Measure coverage PER SERIES: how many series exist in scope, and how many clear
    ``required`` distinct UTC dates of observations.

    Coverage, not span, per ``MinHistoryDays`` — a forecaster needs observations, not calendar
    distance.

    MEASURED AT SERIES GRAIN (``SERIES_GRAIN``), which is the capability's declared grain minus
    the date column. A per-tenant count returns one number for the whole tenant: on a tenant
    with 613 events across 66 (store, sku) pairs at ~9 observations each, it reports the
    tenant's ~80-day calendar and passes a 60-day threshold, while every individual series is
    unforecastable. Per-tenant is not a coarser answer to the same question; it is an answer
    to a different question.

    MEASURED OVER THE SCOPE'S WHOLE HISTORY, not the window a caller asks for: the precondition
    asks whether a series is fit at all, and requesting seven days does not make sixty days of
    history unnecessary.

    ``sku_id`` narrows to ONE series, which is the only case where the measurement is a
    single-series answer rather than a population. Unnarrowed, the two counts describe the
    population and the verdict over them is POLICY — see ``synapse.core.resolution.SeriesPolicy``,
    which this probe deliberately knows nothing about: it is handed a threshold and returns
    counts.

    ``measured_at`` comes from the DATABASE clock in the same transaction as the counts, so the
    timestamp on the report describes the same instant as the numbers beside it.

    Returns an ``Observation`` — measurement only, no verdict.
    """
    counts = probe_statement(scope, store_id=store_id, sku_id=sku_id, required=required)
    identities = qualifying_statement(scope, store_id=store_id, sku_id=sku_id, required=required)

    # ONE TRANSACTION for both, so the counts and the identities describe the same instant. That
    # is what lets Observation assert they agree; across two transactions a healthy race would
    # trip the assertion.
    async with rls_session(engine, scope.tenant_id) as conn:
        pairs_measured, pairs_qualifying, measured_at = (await conn.execute(counts)).one()
        qualifying_rows = (await conn.execute(identities)).all()

    if len(qualifying_rows) > _MAX_SERIES:
        raise ResultTooLargeError(
            f"{len(qualifying_rows)} series clear {required} days for tenant "
            f"{scope.tenant_id}, more than the {_MAX_SERIES} a fetch will narrow by identity. "
            "Truncating would exclude series that qualified; the fix is to push the coverage "
            "predicate into the fetch as a HAVING clause instead of an IN-list"
        )

    return Observation(
        pairs_measured=int(pairs_measured),
        pairs_qualifying=int(pairs_qualifying),
        measured_at=measured_at,
        qualifying=tuple(tuple(str(value) for value in row) for row in qualifying_rows),
    )


__all__ = [
    "DATE_COLUMN",
    "SERIES_GRAIN",
    "probe_min_history_days",
    "probe_statement",
    "qualifying_statement",
    "resolve_daily_series",
]
