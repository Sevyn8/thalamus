"""The last_sale_at resolver, offline. No DB, no engine.

THE LOAD-BEARING TESTS ARE THE SUBTYPE FILTER AND ITS PLACEMENT. Everything else is shape.

- SALE only. A RETURN is stock ARRIVING and a VOID is a sale that did not happen; counting
  either as movement would make a returned SKU look alive. This is a DIFFERENT subtype
  treatment from daily_series, which sums all three into net_quantity, and two capabilities
  over one table disagreeing about the vocabulary is fine as long as each says what it did.
- The filter goes OUTSIDE the collapse. event_subtype is not a dedup-key column, so a
  correction can change it, and filtering inside would let a superseded row survive as the
  "latest" — the same predicate-placement rule as sku_id and the date window in daily_series.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import get_args
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import ClauseElement

from dis_canonical import StoreSkuSaleEvent
from dis_canonical.shared import SaleEventSubtype
from synapse.core.capability import LAST_SALE_AT, CapabilityScope, Freshness, Tenancy
from synapse.core.last_sale_at import LastSaleAtRow
from synapse.resolvers import last_sale_at as resolver_module
from synapse.resolvers._collapse import collapse_latest_wins
from synapse.resolvers.last_sale_at import (
    _AGGREGATE_COLUMNS,
    _COLUMNS,
    _EVENT_TIME_COLUMN,
    _GRAIN,
    _MOVEMENT_SUBTYPES,
    _as_date,
    _check_aggregate_columns,
    _key_scoped_predicate,
    _project,
    _sale_events,
)

TENANT = UUID("019e5e3c-b5d6-7eed-93f9-3778a7a7a160")
STORE = UUID("019e5e3c-b633-7344-93c7-83fb205285ea")
SCOPE = CapabilityScope(tenant_id=TENANT)


def _sql(statement: ClauseElement) -> str:
    compiled = statement.compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
    return re.sub(r"\s+", " ", str(compiled))


def _resolver_sql(*, store_id: UUID | None = None, sku_id: str | None = None) -> str:
    """Rebuild the resolver's statement from its own building blocks, so this cannot drift
    into testing a different query than the resolver runs."""
    from sqlalchemy import ColumnElement, and_, func

    collapsed = collapse_latest_wins(
        _sale_events,
        event_time_column=_EVENT_TIME_COLUMN,
        where=_key_scoped_predicate(SCOPE, store_id),
    )
    filters: list[ColumnElement[bool]] = [collapsed.c.event_subtype.in_(_MOVEMENT_SUBTYPES)]
    if sku_id is not None:
        filters.append(collapsed.c.sku_id == sku_id)
    group_columns = tuple(collapsed.c[name] for name in _GRAIN)
    return _sql(
        select(*group_columns, func.max(collapsed.c.event_date).label("last_sale_date"))
        .where(and_(*filters))
        .group_by(*group_columns)
    )


def _split_at_subquery(sql: str) -> tuple[str, str]:
    inside, _, outside = sql.partition(") AS collapsed")
    return inside, outside


# ---------------------------------------------------------------------------
# The subtype filter
# ---------------------------------------------------------------------------


def test_only_sales_count_as_movement() -> None:
    """RETURN and VOID are excluded, and this is the whole semantic of the capability."""
    assert _MOVEMENT_SUBTYPES == ("SALE",)


def test_the_excluded_subtypes_are_the_rest_of_canonicals_vocabulary() -> None:
    """LOAD-BEARING. Pinned against dis-canonical's Literal so a widened vocabulary forces a
    DECISION about whether the new subtype is movement, rather than silently defaulting to
    'not movement' because the tuple was written before it existed."""
    vocabulary = set(get_args(SaleEventSubtype))
    assert set(_MOVEMENT_SUBTYPES) <= vocabulary
    assert vocabulary - set(_MOVEMENT_SUBTYPES) == {"RETURN", "VOID"}, (
        "canonical's sale-event vocabulary changed; decide whether the new subtype is movement"
    )


def test_the_subtype_filter_is_applied_outside_the_collapse() -> None:
    """event_subtype is not a dedup-key column, so a correction can change it. Filtered inside,
    the collapse would see only the pre-correction row and declare it the latest."""
    inside, outside = _split_at_subquery(_resolver_sql())
    assert "collapsed.event_subtype IN" in outside
    assert "canonical.store_sku_sale_events.event_subtype IN" not in inside


def test_the_tenant_predicate_is_applied_inside_the_collapse() -> None:
    """Safe, because tenant_id is a dedup-key component — and it keeps the collapse on an
    index range rather than sorting every tenant's history."""
    inside, _ = _split_at_subquery(_resolver_sql())
    assert "canonical.store_sku_sale_events.tenant_id = " in inside


def test_the_sku_filter_is_applied_outside_the_collapse() -> None:
    inside, outside = _split_at_subquery(_resolver_sql(sku_id="SKU-000123"))
    assert "collapsed.sku_id = " in outside
    assert "canonical.store_sku_sale_events.sku_id = " not in inside


def test_the_store_filter_is_applied_inside_the_collapse() -> None:
    inside, _ = _split_at_subquery(_resolver_sql(store_id=STORE))
    assert "canonical.store_sku_sale_events.store_id = " in inside


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


def test_it_groups_by_the_declared_grain() -> None:
    group_by = _resolver_sql().rsplit("GROUP BY", 1)[1]
    assert group_by.strip().startswith(", ".join(f"collapsed.{name}" for name in _GRAIN))


def test_it_takes_the_max_event_date() -> None:
    """MAX(event_date), not MAX(source_sale_timestamp): the contract promises a UTC day, which
    is the grain canonical's CHECK constraint actually guarantees."""
    sql = _resolver_sql()
    assert "max(collapsed.event_date) AS last_sale_date" in sql


def test_no_date_window_is_applied() -> None:
    """A window would turn 'last sold 400 days ago' into 'no row', which the only consumer
    reads as 'never sold' — a different and stronger claim."""
    sql = _resolver_sql()
    assert "event_date >=" not in sql
    assert "event_date <=" not in sql


def test_the_column_list_is_derived_from_the_canonical_model() -> None:
    assert set(_COLUMNS) == set(StoreSkuSaleEvent.model_fields)


def test_the_aggregate_column_check_bites(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resolver_module, "_COLUMNS", tuple(c for c in _COLUMNS if c != "event_date"))
    with pytest.raises(ValueError, match="event_date"):
        _check_aggregate_columns()


def test_the_aggregate_columns_all_exist_today() -> None:
    assert set(_AGGREGATE_COLUMNS) <= set(StoreSkuSaleEvent.model_fields)


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


def _row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "tenant_id": TENANT,
        "store_id": STORE,
        "sku_id": "SKU-000123",
        "last_sale_date": date(2026, 5, 12),
    }
    base.update(overrides)
    return base


def test_a_row_projects() -> None:
    row = _project(_row())
    assert isinstance(row, LastSaleAtRow)
    assert row.last_sale_date == date(2026, 5, 12)


def test_a_datetime_is_not_accepted_as_a_date() -> None:
    """datetime subclasses date, so a plain isinstance check would let a timestamp describe
    what the contract promises is a UTC day."""
    with pytest.raises(ValueError, match="expected a plain date"):
        _as_date(datetime(2026, 5, 12, 14, 30, tzinfo=UTC))


def test_a_null_date_fails_loudly() -> None:
    """MAX over a non-empty group of a NOT NULL column cannot be NULL, so None means the query
    is not the query this function thinks it is."""
    with pytest.raises(ValueError, match="cannot be NULL"):
        _as_date(None)


# ---------------------------------------------------------------------------
# The descriptor
# ---------------------------------------------------------------------------


def test_returns_is_the_projection_not_a_parallel_list() -> None:
    assert set(LAST_SALE_AT.returns) == set(LastSaleAtRow.__dataclass_fields__)


def test_it_declares_no_gates() -> None:
    """One observation is enough to answer 'when did this last sell'."""
    assert LAST_SALE_AT.gates == ()


def test_it_is_last_write_not_as_of_date() -> None:
    """Its VALUE is a date; no date PARAMETER is meaningful."""
    assert LAST_SALE_AT.freshness is Freshness.LAST_WRITE
    assert LAST_SALE_AT.tenancy is Tenancy.TENANT_SCOPED


def test_it_returns_exactly_the_grain_plus_one_fact() -> None:
    """Deliberately minimal. The underlying timestamp and a count of selling days are both free
    in the same aggregate, which is not a reason to return them — that is how a capability
    accretes into the god-object this one was split out to avoid."""
    assert len(LAST_SALE_AT.returns) == 4
    assert set(LAST_SALE_AT.grain) < set(LAST_SALE_AT.returns)


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
            / "last_sale_at.json"
        ).read_text(encoding="utf-8")
    )
    assert fixture["id"] == LAST_SALE_AT.id
    assert fixture["version"] == LAST_SALE_AT.version
    assert tuple(fixture["grain"]) == LAST_SALE_AT.grain
    assert fixture["freshness"] == LAST_SALE_AT.freshness.value
    assert set(fixture["returns"]) == set(LAST_SALE_AT.returns)
    assert fixture["gates"] == []
