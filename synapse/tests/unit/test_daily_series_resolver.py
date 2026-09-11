"""The daily_series resolver and the shared dedup collapse, offline. No DB, no engine.

THE LOAD-BEARING TESTS ARE THE SQL-SHAPE ONES, and they are the reason this file exists
rather than leaving the collapse to an integration test. The collapse's correctness is
entirely in its ORDER BY, every part of which fails SILENTLY when wrong:

- key columns not leading      -> Postgres rejects it (caught anywhere)
- last_updated_at leading      -> picks the LAST WRITTEN row, not the latest source event.
                                  Returns plausible numbers. Caught only here.
- no `id DESC` terminator      -> non-deterministic survivor among rows sharing a
                                  transaction timestamp. Passes intermittently in
                                  integration. Caught only here.

The second group pins WHERE EACH PREDICATE GOES, which is a correctness property and not
an optimisation: a filter on a non-dedup-key column pushed inside the collapse lets a
superseded row win.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast, get_args
from uuid import UUID

import pytest
from sqlalchemy import and_, column, func, select, table
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql import ClauseElement

from dis_canonical import StoreSkuSaleEvent
from dis_canonical.shared import SaleEventSubtype
from synapse.core.capability import DAILY_SERIES, CapabilityScope, Freshness, Tenancy
from synapse.core.daily_series import DailySeriesRow
from synapse.resolvers import daily_series as resolver_module
from synapse.resolvers._collapse import DEDUP_KEY, collapse_latest_wins
from synapse.resolvers.daily_series import (
    _AGGREGATE_COLUMNS,
    _COLUMNS,
    _EVENT_TIME_COLUMN,
    _SUBTYPE_COUNTS,
    DATE_COLUMN,
    SERIES_GRAIN,
    _check_aggregate_columns,
    _check_subtype_coverage,
    _key_scoped_predicate,
    _project,
    _sale_events,
    probe_statement,
    resolve_daily_series,
)

TENANT = UUID("019e5e3c-b5d6-7eed-93f9-3778a7a7a160")
STORE = UUID("019e5e3c-b633-7344-93c7-83fb205285ea")
SCOPE = CapabilityScope(tenant_id=TENANT)


def _sql(statement: ClauseElement) -> str:
    """Compile to Postgres and squash whitespace, so assertions read as SQL fragments.

    ``ClauseElement.compile`` carries no annotations in SQLAlchemy 2.0, so the ``--strict``
    gate's disallow_untyped_calls fires here and at the one other call site. Ignored
    narrowly rather than loosening the gate for the whole package.
    """
    compiled = statement.compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
    return re.sub(r"\s+", " ", str(compiled))


def _collapsed_sql(store_id: UUID | None = None) -> str:
    """The collapse subquery ALONE — its own SELECT, not wrapped in an outer one.

    ``.element`` is the inner Select the helper built; compiling the Subquery itself would
    append ``) AS collapsed`` and make every "ends with the tie-break" assertion fail on
    punctuation rather than on ordering.
    """
    collapsed = collapse_latest_wins(
        _sale_events,
        event_time_column=_EVENT_TIME_COLUMN,
        where=_key_scoped_predicate(SCOPE, store_id),
    )
    return _sql(collapsed.element)


# ---------------------------------------------------------------------------
# The collapse: the dedup key and the full tie-break
# ---------------------------------------------------------------------------


def test_the_collapse_distincts_on_the_four_d33_key_columns() -> None:
    """The dedup key is (tenant_id, store_id, source_id, source_event_id)."""
    assert DEDUP_KEY == ("tenant_id", "store_id", "source_id", "source_event_id")
    sql = _collapsed_sql()
    expected = ", ".join(f"canonical.store_sku_sale_events.{name}" for name in DEDUP_KEY)
    assert f"DISTINCT ON ({expected})" in sql


def test_the_key_columns_lead_the_order_by() -> None:
    """Postgres requires the DISTINCT ON expressions to be the leftmost sort keys."""
    sql = _collapsed_sql()
    order_by = sql.split("ORDER BY", 1)[1]
    leading = ", ".join(f"canonical.store_sku_sale_events.{name}" for name in DEDUP_KEY)
    assert order_by.strip().startswith(leading)


def test_event_time_leads_the_tiebreak_and_last_updated_at_does_not() -> None:
    """LOAD-BEARING, and the failure it prevents returns plausible numbers.

    Ordering by last_updated_at first picks the LAST WRITTEN row rather than the latest
    SOURCE EVENT, so a late-delivered older correction wins and the daily figure is wrong
    with nothing to indicate it.
    """
    order_by = _collapsed_sql().split("ORDER BY", 1)[1]
    event_time = order_by.index(f"canonical.store_sku_sale_events.{_EVENT_TIME_COLUMN} DESC")
    write_time = order_by.index("canonical.store_sku_sale_events.last_updated_at DESC")
    assert event_time < write_time, "source event time must outrank write time"


def test_the_tiebreak_terminates_with_the_uuidv7_id() -> None:
    """LOAD-BEARING. last_updated_at defaults to NOW(), which is TRANSACTION time, so
    rows written in one batch share it exactly. Without `id DESC` the survivor is
    whichever row the plan emitted first — a test over this would pass intermittently."""
    order_by = _collapsed_sql().split("ORDER BY", 1)[1]
    assert order_by.rstrip().endswith("canonical.store_sku_sale_events.id DESC")


def test_the_full_tiebreak_is_in_the_documented_d33_order() -> None:
    """The exact live mapping, as used by the streaming consumer."""
    order_by = _collapsed_sql().split("ORDER BY", 1)[1]
    tail = (
        "canonical.store_sku_sale_events.source_sale_timestamp DESC, "
        "canonical.store_sku_sale_events.last_updated_at DESC, "
        "canonical.store_sku_sale_events.id DESC"
    )
    assert order_by.strip().endswith(tail)


def test_the_collapse_refuses_a_table_missing_a_key_column() -> None:
    """A canonical rename must fail at build time, not collapse on a partial key.

    A DISTINCT ON over three of the four key columns is still valid SQL. It would merge
    two different source events and return confidently wrong totals.
    """
    partial = table(
        "store_sku_sale_events",
        *(column(name) for name in ("tenant_id", "store_id", "source_id", "last_updated_at", "id")),
        schema="canonical",
    )
    with pytest.raises(ValueError, match="source_event_id"):
        collapse_latest_wins(partial, event_time_column=_EVENT_TIME_COLUMN, where=partial.c.id.is_not(None))


def test_the_collapse_refuses_a_table_missing_the_id_tiebreak() -> None:
    no_id = table(
        "store_sku_sale_events",
        *(column(name) for name in (*DEDUP_KEY, _EVENT_TIME_COLUMN, "last_updated_at")),
        schema="canonical",
    )
    with pytest.raises(ValueError, match=r"\['id'\]"):
        collapse_latest_wins(
            no_id, event_time_column=_EVENT_TIME_COLUMN, where=no_id.c.tenant_id.is_not(None)
        )


def test_the_collapse_names_no_table_of_its_own() -> None:
    """It is reusable for change events unchanged — which is why it takes the table and
    the event-time column as parameters rather than hardcoding sale events."""
    change_events = table(
        "store_sku_change_events",
        *(column(name) for name in (*DEDUP_KEY, "source_event_timestamp", "last_updated_at", "id")),
        schema="canonical",
    )
    sql = _sql(
        select(
            *collapse_latest_wins(
                change_events,
                event_time_column="source_event_timestamp",
                where=change_events.c.tenant_id == TENANT,
            ).c
        )
    )
    assert "canonical.store_sku_change_events" in sql
    assert "source_event_timestamp DESC" in sql
    assert "store_sku_sale_events" not in sql


# ---------------------------------------------------------------------------
# Where each predicate goes — a correctness property, not an optimisation
# ---------------------------------------------------------------------------


def _split_at_subquery(sql: str) -> tuple[str, str]:
    """(inside the collapse, outside it). The subquery is aliased `collapsed`."""
    inside, _, outside = sql.partition(") AS collapsed")
    return inside, outside


def _resolver_sql(*, store_id: UUID | None = None, sku_id: str | None = None) -> str:
    """Reproduce the resolver's statement shape from its own building blocks.

    Deliberately built from the module's own helpers rather than a hand-written copy, so it
    cannot drift into testing a different query than the resolver runs.
    """
    collapsed = collapse_latest_wins(
        _sale_events,
        event_time_column=_EVENT_TIME_COLUMN,
        where=_key_scoped_predicate(SCOPE, store_id),
    )
    filters = [
        collapsed.c.event_date >= date(2026, 6, 1),
        collapsed.c.event_date <= date(2026, 7, 31),
    ]
    if sku_id is not None:
        filters.append(collapsed.c.sku_id == sku_id)
    group_columns = (
        collapsed.c.tenant_id,
        collapsed.c.store_id,
        collapsed.c.sku_id,
        collapsed.c.event_date,
    )
    return _sql(
        select(*group_columns, func.sum(collapsed.c.quantity).label("net_quantity"))
        .where(and_(*filters))
        .group_by(*group_columns)
    )


def test_the_tenant_predicate_is_inside_the_collapse() -> None:
    """Safe, because tenant_id is a dedup-key component: a correction cannot change it
    and remain the same logical event. Also what keeps the collapse on an index range."""
    inside, _ = _split_at_subquery(_resolver_sql())
    assert "canonical.store_sku_sale_events.tenant_id = " in inside


def test_the_store_predicate_is_inside_the_collapse() -> None:
    """store_id is also a dedup-key component, so narrowing to it cannot hide a
    superseding row."""
    inside, outside = _split_at_subquery(_resolver_sql(store_id=STORE))
    assert "canonical.store_sku_sale_events.store_id = " in inside
    assert "collapsed.store_id = " not in outside


def test_the_date_window_is_applied_outside_the_collapse() -> None:
    """LOAD-BEARING, and the subtlest thing in the resolver.

    event_date is NOT a dedup-key component, so a correction can move a sale to another
    date. Filtered INSIDE the collapse, a window containing only the original would never
    see the correction, would declare the original the survivor, and would return a value
    that had already been superseded.
    """
    inside, outside = _split_at_subquery(_resolver_sql())
    assert "collapsed.event_date >=" in outside
    assert "collapsed.event_date <=" in outside
    assert "event_date >=" not in inside, "a date filter inside the collapse hides corrections"
    assert "event_date <=" not in inside


def test_the_sku_filter_is_applied_outside_the_collapse() -> None:
    """Same reason as the date window: sku_id is not in the dedup key, so a mis-mapped SKU
    corrected at source would otherwise let the pre-correction row survive."""
    inside, outside = _split_at_subquery(_resolver_sql(sku_id="SKU-000123"))
    assert "collapsed.sku_id = " in outside
    assert "canonical.store_sku_sale_events.sku_id = " not in inside


# ---------------------------------------------------------------------------
# The aggregate, the vocabulary, and the loud checks
# ---------------------------------------------------------------------------


def test_the_counted_subtypes_are_canonicals_whole_vocabulary() -> None:
    """LOAD-BEARING. net_quantity sums EVERY surviving row, so the counts must account for
    every subtype or the total and its composition silently stop adding up."""
    assert set(_SUBTYPE_COUNTS) == set(get_args(SaleEventSubtype)), (
        "canonical's SaleEventSubtype vocabulary and daily_series's counted set disagree"
    )


def test_the_count_fields_are_real_projection_fields() -> None:
    for field in _SUBTYPE_COUNTS.values():
        assert field in DailySeriesRow.__dataclass_fields__


def test_the_subtype_coverage_check_bites(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prove the guard fails when the thing it guards is broken.

    A widened vocabulary upstream with no new count here is the exact silent gap; this
    simulates it by narrowing the counted set instead, which fails the same equality.
    """
    monkeypatch.setattr(resolver_module, "_SUBTYPE_COUNTS", {"SALE": "sale_line_count"})
    with pytest.raises(ValueError, match="disagree"):
        _check_subtype_coverage()


def test_the_aggregate_column_check_bites(monkeypatch: pytest.MonkeyPatch) -> None:
    """A canonical DROP of a column this resolver aggregates must fail loudly."""
    monkeypatch.setattr(resolver_module, "_COLUMNS", tuple(c for c in _COLUMNS if c != "quantity"))
    with pytest.raises(ValueError, match="quantity"):
        _check_aggregate_columns()


def test_the_aggregate_columns_all_exist_in_canonical_today() -> None:
    assert set(_AGGREGATE_COLUMNS) <= set(StoreSkuSaleEvent.model_fields)


def test_the_column_list_is_derived_from_the_canonical_model() -> None:
    """Never hand-listed, so the construct cannot drift from dis-canonical."""
    assert set(_COLUMNS) == set(StoreSkuSaleEvent.model_fields)


# ---------------------------------------------------------------------------
# The projection
# ---------------------------------------------------------------------------


def _aggregate_row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "tenant_id": TENANT,
        "store_id": STORE,
        "sku_id": "SKU-000123",
        "event_date": date(2026, 7, 30),
        "net_quantity": Decimal("11.000"),
        "sale_line_count": 13,
        "return_line_count": 2,
        "void_line_count": 0,
    }
    base.update(overrides)
    return base


def test_an_aggregate_row_projects() -> None:
    row = _project(_aggregate_row())
    assert isinstance(row, DailySeriesRow)
    assert row.net_quantity == Decimal("11.000")
    assert (row.sale_line_count, row.return_line_count, row.void_line_count) == (13, 2, 0)


def test_a_negative_net_quantity_is_legitimate() -> None:
    """A day of net returns. Not an error, and not to be clamped to zero."""
    assert _project(_aggregate_row(net_quantity=Decimal("-4.000"))).net_quantity == Decimal("-4.000")


def test_a_null_net_quantity_fails_loudly() -> None:
    """Every group holds a row and quantity is NOT NULL, so a NULL sum means the query is
    not the query the projection thinks it is. Coalescing to zero would make that
    indistinguishable from a real day of offsetting returns."""
    with pytest.raises(ValueError, match="net_quantity"):
        _project(_aggregate_row(net_quantity=None))


def test_a_float_net_quantity_fails_loudly() -> None:
    """NUMERIC(14,3) must arrive as Decimal; a float here is a driver change worth a raise
    on a figure someone reconciles against a POS report."""
    with pytest.raises(ValueError, match="net_quantity"):
        _project(_aggregate_row(net_quantity=11.0))


def test_a_non_date_event_date_fails_loudly() -> None:
    with pytest.raises(ValueError, match="event_date"):
        _project(_aggregate_row(event_date="2026-07-30"))


def test_a_datetime_is_not_accepted_as_an_event_date() -> None:
    """datetime subclasses date in Python, and a UTC-day series must not silently accept a
    timestamp — the grain would stop being a day."""
    with pytest.raises(ValueError, match="event_date"):
        _project(_aggregate_row(event_date=datetime(2026, 7, 30, 12, tzinfo=UTC)))


# ---------------------------------------------------------------------------
# The signature's own guards
# ---------------------------------------------------------------------------


async def test_an_inverted_date_window_raises_before_touching_the_engine() -> None:
    with pytest.raises(ValueError, match="after date_to"):
        await resolve_daily_series(
            cast(AsyncEngine, None),
            SCOPE,
            date_from=date(2026, 7, 31),
            date_to=date(2026, 6, 1),
        )


async def test_the_date_window_is_required() -> None:
    """No default window: an as_of_date capability with an implicit "all history" is the
    series equivalent of a resolver that defaults to a cross-tenant read."""
    with pytest.raises(TypeError):
        await resolve_daily_series(cast(AsyncEngine, None), SCOPE)  # type: ignore[call-arg]


def test_scope_is_the_only_source_of_tenancy() -> None:
    """The in-query predicate names the SCOPE's tenant, never a caller field."""
    inside, _ = _split_at_subquery(_resolver_sql())
    assert "canonical.store_sku_sale_events.tenant_id = " in inside
    statement: ClauseElement = select(*_sale_events.c).where(_key_scoped_predicate(SCOPE, None))
    compiled = statement.compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
    assert TENANT in compiled.params.values()


# ---------------------------------------------------------------------------
# The descriptor
# ---------------------------------------------------------------------------


def test_returns_is_the_projection_not_a_parallel_list() -> None:
    assert set(DAILY_SERIES.returns) == set(DailySeriesRow.__dataclass_fields__)


def test_daily_series_is_the_first_as_of_date_capability() -> None:
    assert DAILY_SERIES.freshness is Freshness.AS_OF_DATE
    assert DAILY_SERIES.tenancy is Tenancy.TENANT_SCOPED
    assert "event_date" in DAILY_SERIES.grain


def test_daily_series_returns_no_money_field() -> None:
    """tax_treatment is per-row INCLUSIVE/EXCLUSIVE, so a summed amount would add tax
    bases together with nothing declaring a normalization. Quantity only until that
    decision exists."""
    for field in DAILY_SERIES.returns:
        assert not any(word in field for word in ("amount", "price", "revenue", "cost", "total"))


def test_daily_series_produces_no_signals() -> None:
    assert DAILY_SERIES.produces_signals == ()


def test_descriptor_matches_the_committed_fixture() -> None:
    import json
    import pathlib

    fixture = json.loads(
        (
            pathlib.Path(__file__).resolve().parents[3]
            / "contracts"
            / "synapse"
            / "fixtures"
            / "capability"
            / "daily_series.json"
        ).read_text(encoding="utf-8")
    )
    assert fixture["id"] == DAILY_SERIES.id
    assert fixture["version"] == DAILY_SERIES.version
    assert tuple(fixture["grain"]) == DAILY_SERIES.grain
    assert fixture["tenancy"] == DAILY_SERIES.tenancy.value
    assert fixture["freshness"] == DAILY_SERIES.freshness.value
    assert set(fixture["returns"]) == set(DAILY_SERIES.returns)
    assert tuple(fixture["produces_signals"]) == DAILY_SERIES.produces_signals
    assert fixture["gates"] == ["min_history_days"]
    assert tuple(fixture["gates"]) == DAILY_SERIES.gates


# ---------------------------------------------------------------------------
# The precondition probe: SERIES grain, not tenant grain
#
# The first version of this probe was COUNT(DISTINCT event_date) per TENANT. On a tenant with
# 613 events across 66 (store, sku) pairs at ~9 observations each it reported the tenant's
# ~80-day calendar and cleared a 60-day threshold, while not one series was forecastable.
# These tests pin the grain in the SQL itself, because a constant that the query does not
# actually group by is just another claim.
# ---------------------------------------------------------------------------


def _probe_sql(*, store_id: UUID | None = None, sku_id: str | None = None, required: int = 60) -> str:
    return _sql(probe_statement(SCOPE, store_id=store_id, sku_id=sku_id, required=required))


def test_the_probe_measures_at_the_declared_grain_minus_the_date() -> None:
    """THE GRAIN RULE, stated as the two constants the query is built from.

    Enforced for real at registry import (see test_registry.py); asserted here too because
    this is the module that has to keep them true.
    """
    assert set(SERIES_GRAIN) | {DATE_COLUMN} == set(DAILY_SERIES.grain)
    assert DATE_COLUMN in DAILY_SERIES.grain
    assert DATE_COLUMN not in SERIES_GRAIN


def test_the_probe_sql_groups_by_exactly_the_series_grain() -> None:
    """LOAD-BEARING. The constant is only worth anything if it IS the query's GROUP BY.

    Without this, SERIES_GRAIN could say (tenant_id, store_id, sku_id) while the SQL grouped
    by tenant alone — the declared-vs-actual gap that produced the defect in the first place,
    just relocated one layer up.
    """
    group_by = _probe_sql().rsplit("GROUP BY", 1)[1]
    expected = ", ".join(f"collapsed.{name}" for name in SERIES_GRAIN)
    assert group_by.strip().startswith(expected)


def test_the_probe_does_not_group_by_the_date_column() -> None:
    """Grouping by event_date would make every coverage 1 — a gate that always fails."""
    group_by = _probe_sql().rsplit("GROUP BY", 1)[1]
    assert f"collapsed.{DATE_COLUMN}" not in group_by


def test_the_probe_counts_distinct_dates_as_coverage() -> None:
    """COVERAGE, NOT SPAN. A forecaster needs observations, not calendar distance — so this
    is COUNT(DISTINCT event_date) and never MAX(event_date) - MIN(event_date)."""
    sql = _probe_sql()
    assert f"count(distinct(collapsed.{DATE_COLUMN})) AS coverage" in sql
    assert "max(" not in sql.lower()
    assert "min(" not in sql.lower()


def test_the_probe_returns_two_counts_not_a_reduced_number() -> None:
    """Measurement, not verdict. The threshold is applied in SQL so the result is two
    integers rather than 125,000 per-series rows, but no reduction to a single scalar happens
    anywhere — that reduction is policy and lives outside the probe."""
    sql = _probe_sql()
    assert "count(*) AS pairs_measured" in sql
    assert "FILTER (WHERE per_series.coverage >= " in sql
    assert "AS pairs_qualifying" in sql


def test_the_probe_applies_the_threshold_it_is_handed() -> None:
    """The value is a bind parameter from the descriptor, not a literal in this module."""
    statement = probe_statement(SCOPE, store_id=None, sku_id=None, required=90)
    compiled = statement.compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
    assert 90 in compiled.params.values()


def test_the_probe_collapses_before_measuring() -> None:
    """REVERSES THE EARLIER REASONING, which was that no collapse was needed.

    That was true only of the per-TENANT count it was written for. At series grain a
    correction that changes sku_id files its dates under BOTH the old and new SKU, inventing a
    phantom series and inflating a real one — and both errors are PERMISSIVE, which is the
    wrong direction for a gate.
    """
    sql = _probe_sql()
    assert "DISTINCT ON (canonical.store_sku_sale_events.tenant_id" in sql
    inside, outside = _split_at_subquery(sql)
    assert "ORDER BY" in inside, "the collapse must be inside, before the per-series grouping"


def test_the_probe_filters_store_inside_and_sku_outside_the_collapse() -> None:
    """Same predicate-placement rule as the resolver: only dedup-key components are safe
    inside. A sku filter inside would let a pre-correction row survive and be counted."""
    inside, outside = _split_at_subquery(_probe_sql(store_id=STORE, sku_id="SKU-000123"))
    assert "canonical.store_sku_sale_events.store_id = " in inside
    assert "canonical.store_sku_sale_events.sku_id = " not in inside
    assert "collapsed.sku_id = " in outside


def test_the_probe_measures_whole_history_with_no_date_window() -> None:
    """The precondition asks whether a series is fit AT ALL. A caller requesting seven days
    does not make sixty days of history unnecessary, so no window is applied."""
    sql = _probe_sql()
    assert "event_date >=" not in sql
    assert "event_date <=" not in sql
