"""GET /alerts and GET /alerts/state-counts: the fleet inbox and its filter chips.

TWO ENDPOINTS, ONE DERIVATION. The list filters on lifecycle state and the chips group by it.
If those were two SQL expressions they would drift, and a chip that disagrees with the list it
filters is worse than no chip: it reads as a count of something and is a count of nothing.
``_LIFECYCLE_STATE`` is the single construct, asserted below to appear in both statements.

THE VIEW, NOT THE TABLE. Both read ``synapse.actions_analytical``. The tenant-scoped alert list
reads the base table and is fine there, because the sentinel fixture tenant is only reachable by
navigating to it on purpose. Fleet-wide, its immortal probe rows would land in the DEFAULT view
and in every chip count, arriving from a tenant nobody would think to check.

NO DATABASE. A recording fake drives the reader so the SQL, the session scope and the filter
binding are all asserted offline; the RLS behaviour the fake stands in for is the integration
suite's job.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from synapse_ui_server import reads

TENANT = UUID("019fb16b-e402-7dce-b026-6fa9f4919242")
STORE = UUID("019fb250-d099-7221-ab04-68f65fe68287")
EVENT = UUID("019fb16b-0000-7000-8000-00000000ab01")
# The quarantined fixture tenant, seeded by migration 0007.
SENTINEL = "decafbad-0000-4000-8000-000000000001"


def _engine() -> AsyncEngine:
    """A sentinel where an engine is expected, typed for mypy. Never touched: every test patches
    rls_platform_session, which is the only thing that would open a connection."""
    return cast("AsyncEngine", object())


def _row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "event_id": EVENT,
        "tenant_id": TENANT,
        "tenant_name": "The Body Shop",
        "as_of": date(2026, 8, 9),
        "recorded_at": datetime(2026, 8, 9, 3, 0, tzinfo=UTC),
        "declaration_id": "stockout_risk",
        "quantity_at_stake": Decimal("16.000"),
        "days_since_last_sale": None,
        "days_of_cover": Decimal("5.040"),
        "store_id": STORE,
        "sku_id": "SKU-0001",
        "store_name": "Promnade VK",
        "product_name": "Vitamin C Serum 30ml",
        "lifecycle_state": "open",
        "lifecycle_reason": None,
        "lifecycle_snoozed_until": None,
    }
    base.update(overrides)
    return base


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeResult:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _RecordingConn:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self._rows = rows if rows is not None else [_row()]

    async def execute(self, statement: object, params: dict[str, Any] | None = None) -> _FakeResult:
        self.calls.append((str(statement), params))
        return _FakeResult(self._rows)


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Swap rls_platform_session at the MODULE, so reads.py's own call site is under test. A
    test patching elsewhere could pass while reads.py opened a raw connection, which against
    FORCE ROW LEVEL SECURITY returns zero rows and raises nothing."""

    def install(conn: _RecordingConn) -> None:
        @asynccontextmanager
        async def fake(engine: object, tenant: object):  # type: ignore[no-untyped-def]
            conn.opened_with = (engine, tenant)  # type: ignore[attr-defined]
            yield conn

        monkeypatch.setattr(reads, "rls_platform_session", fake)

    return install


# ---------------------------------------------------------------------------
# Amendment 1: the quarantine
# ---------------------------------------------------------------------------


def test_both_fleet_queries_read_the_analytical_view() -> None:
    """THE AMENDMENT, pinned on the SQL. synapse.actions_analytical excludes every tenant in
    synapse.quarantined_tenants, which is how the sentinel's immortal probe rows stay out of a
    surface that shows everything by default."""
    for statement in (reads._FLEET_ALERTS, reads._FLEET_ALERT_STATE_COUNTS):
        sql = str(statement)
        assert "synapse.actions_analytical" in sql
        assert "FROM synapse.actions a" not in sql, "the fleet query reads the base table"


def test_the_sentinel_tenant_cannot_reach_either_endpoint() -> None:
    """The exclusion is the VIEW's, not a predicate this code could forget. Asserted by showing
    neither statement names the sentinel and both go through the view, so there is no filter to
    omit: a row under a quarantined tenant is not in the relation being read at all."""
    for statement in (reads._FLEET_ALERTS, reads._FLEET_ALERT_STATE_COUNTS):
        sql = str(statement)
        assert SENTINEL not in sql
        assert "quarantined_tenants" not in sql, (
            "the fleet query filters the sentinel by hand; it should inherit the view's exclusion "
            "so a future tenant added to the registry is covered without editing this SQL"
        )
        assert "synapse.actions_analytical" in sql


# ---------------------------------------------------------------------------
# Amendment 2: the snooze expiry timezone
# ---------------------------------------------------------------------------


def test_the_expiry_comparison_is_explicit_utc_not_current_date() -> None:
    """CURRENT_DATE resolves in the DB session's timezone, which is configuration rather than
    contract. The TypeScript side compares against new Date().toISOString().slice(0,10), which is
    UTC by definition, and DecisionControls mints the expiry the same way. Anchoring the SQL to
    UTC explicitly makes the two agree by construction rather than by both happening to sit in
    the same zone."""
    sql = str(reads._FLEET_ALERTS)
    assert "(now() AT TIME ZONE 'UTC')::date" in sql
    assert "CURRENT_DATE" not in sql, (
        "CURRENT_DATE reintroduces a dependency on the session timezone, which the local devbox "
        "and staging are not guaranteed to share"
    )


def test_a_snooze_lapses_on_the_day_after_its_expiry() -> None:
    """THE DAY BOUNDARY, pinned so a later change to either side breaks something visible.

    The rule both sides implement: snoozed while snoozed_until >= today, open from the day after.
    Expressed here against the SQL's own comparison so the boundary is documented in a test
    rather than only in a CASE arm.
    """
    expiry = date(2026, 8, 16)
    assert expiry >= date(2026, 8, 15), "the day before expiry is still snoozed"
    assert expiry >= date(2026, 8, 16), "expiry day itself is still snoozed"
    assert not (expiry >= date(2026, 8, 17)), "the day after expiry is open again"
    # And the SQL uses >= against a UTC date, which is the same comparison.
    assert "le.snoozed_until >= (now() AT TIME ZONE 'UTC')::date" in str(reads._FLEET_ALERTS)


def test_both_derivations_enumerate_the_same_state_set() -> None:
    """TWO IMPLEMENTATIONS EXIST and this bounds the drift. Filtering has to be SQL, so this
    copy is unavoidable; primitives.tsx alertState() stays as it is because 5c and 5d must not be
    touched. Consolidating is Phase B.

    This cannot prove semantic equivalence across two languages and does not claim to. It catches
    the drift that matters: one side gaining a state the other has never heard of.
    """
    import pathlib
    import re

    sql_states = set(re.findall(r"THEN '([a-z]+)'", str(reads._FLEET_ALERTS)))
    sql_states |= set(re.findall(r"ELSE '([a-z]+)'", str(reads._FLEET_ALERTS)))

    ts = pathlib.Path(__file__).resolve().parents[4] / "cm-frontend/components/synapse/primitives.tsx"
    union = re.search(r"export type AlertState =([^;]+);", ts.read_text(encoding="utf-8"))
    assert union is not None, "AlertState union not found; the TS derivation moved"
    ts_states = set(re.findall(r'"([a-z]+)"', union.group(1)))

    assert sql_states == ts_states == set(reads.ALERT_STATES), (
        f"SQL says {sorted(sql_states)}, TS says {sorted(ts_states)}, "
        f"ALERT_STATES says {sorted(reads.ALERT_STATES)}"
    )


# ---------------------------------------------------------------------------
# The list
# ---------------------------------------------------------------------------


async def test_the_list_reads_under_the_platform_session(patched) -> None:  # type: ignore[no-untyped-def]
    """synapse.actions is FORCE ROW LEVEL SECURITY, and the view is security_invoker, so a
    session without app.user_type matches ZERO rows and raises nothing."""
    conn = _RecordingConn()
    patched(conn)
    await reads.fleet_alerts(_engine())
    assert conn.opened_with[1] is None, "the session must be PLATFORM (tenant=None)"  # type: ignore[attr-defined]


async def test_every_filter_reaches_the_driver_as_a_bind_parameter(patched) -> None:  # type: ignore[no-untyped-def]
    """Bound, never interpolated: these are caller-supplied values on a PLATFORM endpoint that
    sees every tenant."""
    conn = _RecordingConn()
    patched(conn)
    await reads.fleet_alerts(
        _engine(), state="snoozed", analysis_id="dead_stock", tenant_id=TENANT, store_id=STORE, limit=10
    )
    _sql, params = conn.calls[0]
    assert params == {
        "state": "snoozed",
        "analysis": "dead_stock",
        "tenant": str(TENANT),
        "store": str(STORE),
        "limit": 10,
    }


async def test_absent_filters_bind_none_rather_than_being_omitted(patched) -> None:  # type: ignore[no-untyped-def]
    """The statement is one shape with `:x IS NULL OR ...` arms, so an unfiltered call still
    binds every key. Building the WHERE in Python would mean several statements, several plans,
    and string concatenation next to a value."""
    conn = _RecordingConn()
    patched(conn)
    await reads.fleet_alerts(_engine())
    _sql, params = conn.calls[0]
    # NOT A type: ignore. A call that bound no parameters at all would satisfy every
    # assertion below by never reaching them, so the None is ruled out rather than silenced.
    assert params is not None
    assert params["state"] is None and params["tenant"] is None and params["analysis"] is None


@pytest.mark.parametrize(("asked", "expected"), [(10, 10), (500, 500), (501, 500), (0, 1), (-5, 1)])
async def test_the_limit_is_bounded_both_ends(patched, asked: int, expected: int) -> None:  # type: ignore[no-untyped-def]
    conn = _RecordingConn()
    patched(conn)
    await reads.fleet_alerts(_engine(), limit=asked)
    _sql, params = conn.calls[0]
    assert params is not None
    assert params["limit"] == expected


def test_the_ordering_carries_a_unique_tiebreaker() -> None:
    """as_of and recorded_at BOTH tie in practice, because a sweep records a whole slot at once.
    Without event_id, which is the primary key, a LIMIT would duplicate or skip rows at the page
    boundary. Same three keys the tenant-scoped query already uses."""
    sql = str(reads._FLEET_ALERTS)
    assert "ORDER BY x.as_of DESC, x.recorded_at DESC, x.event_id" in sql


async def test_the_row_carries_the_tenant_and_the_derived_state(patched) -> None:  # type: ignore[no-untyped-def]
    conn = _RecordingConn([_row(lifecycle_state="snoozed", lifecycle_snoozed_until=date(2026, 8, 16))])
    patched(conn)
    (row,) = await reads.fleet_alerts(_engine())
    assert row.tenant_name == "The Body Shop"
    assert row.lifecycle_state == "snoozed"
    assert row.lifecycle_snoozed_until == date(2026, 8, 16)


# ---------------------------------------------------------------------------
# The chips
# ---------------------------------------------------------------------------


async def test_the_counts_include_every_state_even_at_zero(patched) -> None:  # type: ignore[no-untyped-def]
    """A chip reading "Acknowledged 0" is a fact. A chip missing because the GROUP BY returned no
    row for that state is an absence the reader cannot tell apart from it."""
    conn = _RecordingConn([{"lifecycle_state": "open", "alerts": 7}])
    patched(conn)
    counts = await reads.alert_state_counts(_engine())
    assert counts == {"open": 7, "snoozed": 0, "acknowledged": 0, "dismissed": 0}


async def test_the_counts_read_under_the_platform_session(patched) -> None:  # type: ignore[no-untyped-def]
    conn = _RecordingConn([])
    patched(conn)
    await reads.alert_state_counts(_engine())
    assert conn.opened_with[1] is None  # type: ignore[attr-defined]


def test_the_counts_query_is_not_paginated() -> None:
    """WHOLE FLEET, deliberately. Deriving chips from the paginated list would understate every
    number the moment the limit bites."""
    sql = str(reads._FLEET_ALERT_STATE_COUNTS)
    assert "LIMIT" not in sql.upper()
    assert "GROUP BY x.lifecycle_state" in sql


def test_both_statements_share_one_state_derivation() -> None:
    """The constraint that keeps the chips honest: the list filters on the same expression the
    chips group by. Asserted by showing the shared constant's distinctive text in both."""
    marker = "WHEN le.verb = 'acknowledge'"
    assert marker in str(reads._FLEET_ALERTS)
    assert marker in str(reads._FLEET_ALERT_STATE_COUNTS)
    assert marker in reads._LIFECYCLE_STATE


# ===========================================================================================
# THE REQUIRED NEGATIVE TEST: a new per-product surface, so the tenant ban is re-asserted
# ===========================================================================================


def test_the_fleet_alert_payload_is_made_of_fields_the_tenant_contract_forbids() -> None:
    """FleetAlertRow is the widest per-product payload in this service: it carries sku_id,
    product_name, store_name AND tenant_name, across every tenant at once. Positively identified
    as forbidden material so the ban is about THIS type rather than a general caution.

    If this ever fails, the fleet row has stopped carrying per-product data and the reason for
    the prohibition has changed, which is a decision rather than a green tick.
    """
    from synapse_ui_server.tenant_view_contract import FORBIDDEN_TENANT_FIELDS

    fields = set(reads.FleetAlertRow.__dataclass_fields__)
    leaking = fields & FORBIDDEN_TENANT_FIELDS
    assert leaking >= {"sku_id", "store_id", "product_name", "store_name"}, (
        f"FleetAlertRow no longer carries the per-product fields the ban exists for; found {leaking}"
    )


def test_the_tenant_read_module_does_not_import_the_fleet_reads() -> None:
    """Arms itself. Skips while synapse_ui_server.tenant is absent and becomes a real assertion
    the moment it exists, rather than being written later by someone who has to remember this
    file. A fleet-wide payload is the single worst thing a tenant-facing surface could reuse."""
    import importlib.util

    from synapse_ui_server.tenant_view_contract import TENANT_READ_MODULE

    spec = importlib.util.find_spec(TENANT_READ_MODULE)
    if spec is None or spec.origin is None:
        pytest.skip(f"{TENANT_READ_MODULE} does not exist yet")
    body = __import__("pathlib").Path(spec.origin).read_text(encoding="utf-8")
    for banned in ("FleetAlertRow", "fleet_alerts", "alert_state_counts"):
        assert banned not in body, f"{TENANT_READ_MODULE} references {banned}"
