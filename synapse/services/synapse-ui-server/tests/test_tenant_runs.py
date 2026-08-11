"""/tenants/{id}/runs — the tenant-scoped run history.

WHAT IT REPLACED AND WHY THAT MATTERED. The tenant page fetched the FLEET-WIDE /runs at its
maximum limit and filtered client-side on tenant_id. That is correct for a small fleet and
silently wrong for a large one: a tenant's older runs get pushed past the cap by OTHER tenants'
activity, and the page cannot tell "this client has no history" from "this client's history fell
off the end". The caption said so on screen, which was honest and is not the same as being right.

TENANT ISOLATION IS THE REQUIRED PROPERTY and it is asserted two ways below — on the SQL (the
predicate exists and is parameterised) and on the behaviour (the tenant actually reaches the
driver, and nothing else does). Neither needs a database.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from synapse_ui_server import reads

TENANT = UUID("019fb16b-e402-7dce-b026-6fa9f4919242")
OTHER = UUID("decafbad-0000-4000-8000-000000000001")


def _engine() -> AsyncEngine:
    """A sentinel where an engine is expected, typed so mypy --strict accepts the call.

    ``reads.tenant_runs`` never touches it: every test below patches ``rls_platform_session``,
    which is the only thing that would open a connection. A real engine would be worse than a
    sentinel here — it would make a passing test consistent with a connection having been made.
    ``cast`` is a no-op at runtime, so this hands over exactly the bare object it always did.
    """
    return cast("AsyncEngine", object())


# ---------------------------------------------------------------------------
# The SQL: the fleet query and the tenant query differ by EXACTLY the filter
# ---------------------------------------------------------------------------


def test_the_tenant_query_filters_on_tenant_id() -> None:
    """The isolation predicate, asserted on the statement itself. Parameterised — a formatted
    tenant id would be an injection surface on a PLATFORM endpoint that sees every tenant."""
    sql = str(reads._TENANT_RUNS)
    assert "WHERE r.tenant_id = CAST(:tenant AS uuid)" in sql
    assert ":tenant" in sql


def test_the_fleet_query_has_no_tenant_filter_and_is_unchanged() -> None:
    """The other half: /runs stays fleet-wide. If this ever gains a WHERE, the fleet page starts
    showing one tenant and nothing says so."""
    assert "WHERE" not in str(reads._RUNS).upper()


def test_the_two_queries_differ_only_by_the_filter() -> None:
    """ONE SHAPE FOR ONE TABLE. Projection, join and ordering must match, or the two lists
    disagree about what a run row IS — a second source of truth for the same rows, which is the
    duplication class this project keeps paying for.

    Compared by normalising whitespace and removing the tenant predicate.
    """
    import re

    def norm(sql: str) -> str:
        return re.sub(r"\s+", " ", sql).strip()

    fleet = norm(str(reads._RUNS))
    tenant = norm(str(reads._TENANT_RUNS)).replace("WHERE r.tenant_id = CAST(:tenant AS uuid) ", "")
    assert fleet == tenant, f"the two run queries have diverged:\n  fleet : {fleet}\n  tenant: {tenant}"


# ---------------------------------------------------------------------------
# The behaviour, with a fake connection — no database
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]] | None) -> None:
        self._rows = rows or []

    def mappings(self) -> _FakeResult:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None


class _RecordingConn:
    """Records every (statement, params) pair and answers from a script."""

    def __init__(self, exists: bool, rows: list[dict[str, Any]]) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._exists = exists
        self._rows = rows

    async def execute(self, statement: object, params: dict[str, Any]) -> _FakeResult:
        self.calls.append((str(statement), params))
        if "identity_mirror.tenants WHERE tenant_id" in str(statement):
            return _FakeResult([{"?column?": 1}] if self._exists else [])
        return _FakeResult(self._rows)


def _row(tenant: UUID, sku_slot: str) -> dict[str, Any]:
    return {
        "run_id": UUID(int=1),
        "tenant_id": tenant,
        "tenant_name": "The Body Shop",
        "analysis_id": "dead_stock",
        "slot": date.fromisoformat(sku_slot),
        "timezone": "Asia/Kolkata",
        "outcome": "satisfied",
        "actions_proposed": 1,
        "actions_appended": 1,
        "started_at": datetime(2026, 8, 6, 3, 0, tzinfo=UTC),
        "finished_at": datetime(2026, 8, 6, 3, 1, tzinfo=UTC),
        # The refusal breakdown reads straight through from JSONB (migration 0005).
        "refusals": {"series_too_stale": 3},
    }


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Swap rls_platform_session for one yielding a recording connection.

    PATCHED AT THE MODULE, not globally: this proves reads.py's own call site is the one under
    test. A test that patched somewhere else could pass while reads.py opened a raw connection —
    which against FORCE ROW LEVEL SECURITY returns zero rows and raises nothing.
    """

    def install(conn: _RecordingConn) -> None:
        @asynccontextmanager
        async def fake(engine: object, tenant: object):  # type: ignore[no-untyped-def]
            conn.opened_with = (engine, tenant)  # type: ignore[attr-defined]
            yield conn

        monkeypatch.setattr(reads, "rls_platform_session", fake)

    return install


async def test_a_tenant_sees_only_its_own_runs(patched) -> None:  # type: ignore[no-untyped-def]
    """THE REQUIRED TEST. The tenant reaches the driver as a bind parameter, and it is the tenant
    that was asked for — not a default, not the first row's, not the fleet."""
    conn = _RecordingConn(exists=True, rows=[_row(TENANT, "2026-08-06")])
    patched(conn)

    rows = await reads.tenant_runs(_engine(), TENANT, limit=10)

    assert rows is not None and len(rows) == 1
    assert rows[0].tenant_id == TENANT

    history = [c for c in conn.calls if "FROM synapse.run" in c[0]]
    assert len(history) == 1, "the history query ran more than once"
    assert history[0][1]["tenant"] == str(TENANT)
    assert str(OTHER) not in history[0][0], "another tenant's id is baked into the statement"


async def test_the_platform_session_is_the_one_used(patched) -> None:  # type: ignore[no-untyped-def]
    """synapse.run is FORCE ROW LEVEL SECURITY: a session without app.user_type matches ZERO rows
    and raises nothing. So "which session" is not a style question — a raw connection would return
    an empty history for every tenant and look like a quiet fleet."""
    conn = _RecordingConn(exists=True, rows=[])
    patched(conn)
    await reads.tenant_runs(_engine(), TENANT)
    assert conn.opened_with[1] is None, "the session must be PLATFORM (tenant=None), not scoped"  # type: ignore[attr-defined]


async def test_an_unknown_tenant_returns_none_not_an_empty_list(patched) -> None:  # type: ignore[no-untyped-def]
    """None is what the route turns into a 404. An empty list for a mistyped id is
    indistinguishable from a real tenant that has never run."""
    conn = _RecordingConn(exists=False, rows=[])
    patched(conn)
    assert await reads.tenant_runs(_engine(), TENANT) is None
    assert not [c for c in conn.calls if "FROM synapse.run" in c[0]], (
        "the history query ran for a tenant that does not exist"
    )


@pytest.mark.parametrize(
    ("asked", "expected"),
    [(10, 10), (100, 100), (500, 500), (501, 500), (99999, 500), (0, 1), (-5, 1)],
)
async def test_the_limit_is_bounded_both_ends(patched, asked: int, expected: int) -> None:  # type: ignore[no-untyped-def]
    """Capped at _MAX_ROWS and floored at 1, matching reads.runs exactly. An unbounded limit on a
    PLATFORM endpoint is a way to pull the whole table through one request."""
    conn = _RecordingConn(exists=True, rows=[])
    patched(conn)
    await reads.tenant_runs(_engine(), TENANT, limit=asked)
    history = [c for c in conn.calls if "FROM synapse.run" in c[0]]
    assert history[0][1]["limit"] == expected


async def test_the_default_limit_matches_the_fleet_endpoint(patched) -> None:  # type: ignore[no-untyped-def]
    conn = _RecordingConn(exists=True, rows=[])
    patched(conn)
    await reads.tenant_runs(_engine(), TENANT)
    history = [c for c in conn.calls if "FROM synapse.run" in c[0]]
    assert history[0][1]["limit"] == 100


# ---------------------------------------------------------------------------
# The route
# ---------------------------------------------------------------------------


def _client(monkeypatch: pytest.MonkeyPatch, result: object) -> Any:
    """An app with auth bypassed and reads.tenant_runs stubbed. The gate itself is tested in
    test_auth.py; stubbing it here keeps this file about routing and the 404."""
    from fastapi.testclient import TestClient
    from synapse_ui_server.auth import Identity, UserType, require_platform
    from synapse_ui_server.config import Config
    from synapse_ui_server.main import create_app

    app = create_app(
        Config(
            reader_url="postgresql+psycopg://u@h/d",
            lifecycle_url="postgresql+psycopg://l@h/d",
            provision_url="postgresql+psycopg://p@h/d",
            cm_api_base_url="https://cm.example",
            jwt_issuer="https://x/",
            jwt_audience="a",
            expected_database="thalamus",
            axon_sender_url="postgresql+psycopg://a@h/d",
            axon_sendgrid_api_key="test-key",
            axon_sendgrid_from_email="noreply@test.invalid",
            axon_platform_oncall_email="oncall@test.invalid",
        )
    )

    async def _stub(engine: object, tenant_id: UUID, *, limit: int = 100) -> object:
        return result

    monkeypatch.setattr(reads, "tenant_runs", _stub)
    app.dependency_overrides[require_platform] = lambda: Identity(
        subject="s", user_type=UserType.PLATFORM, tenant_id=None
    )
    app.state.engine = object()
    return TestClient(app)


def test_the_route_404s_when_the_tenant_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Matching /tenants/{id}. A 200 with an empty list would render as "no runs yet" for a typo."""
    client = _client(monkeypatch, None)
    response = client.get(f"/tenants/{TENANT}/runs")
    assert response.status_code == 404
    assert "identity_mirror.tenants" in response.json()["detail"]


def test_the_route_returns_the_rows_it_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    from synapse_ui_server.reads import RunRow

    row = RunRow(
        run_id=UUID(int=1),
        tenant_id=TENANT,
        tenant_name="The Body Shop",
        analysis_id="dead_stock",
        slot=date(2026, 8, 6),
        timezone="Asia/Kolkata",
        outcome="satisfied",
        actions_proposed=1,
        actions_appended=1,
        started_at=datetime(2026, 8, 6, 3, 0, tzinfo=UTC),
        finished_at=datetime(2026, 8, 6, 3, 1, tzinfo=UTC),
        refusals={"series_too_stale": 3},
    )
    client = _client(monkeypatch, (row,))
    response = client.get(f"/tenants/{TENANT}/runs")
    assert response.status_code == 200
    body = response.json()["runs"]
    assert len(body) == 1
    assert body[0]["tenant_id"] == str(TENANT)
    assert body[0]["timezone"] == "Asia/Kolkata"
    # No per-product field may appear on any synapse_ui_server response.
    assert not {"sku_id", "product_name", "target"} & set(body[0])


def test_the_fleet_route_still_exists_and_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Added ALONGSIDE /runs, not replacing it. The fleet-wide runs page still consumes it."""
    client = _client(monkeypatch, ())
    paths = {r.path for r in client.app.routes if hasattr(r, "path")}
    assert "/runs" in paths
    assert "/tenants/{tenant_id}/runs" in paths


# ---------------------------------------------------------------------------
# The refusal breakdown reaches the console (slice 5b)
# ---------------------------------------------------------------------------


def test_every_run_query_selects_the_refusal_breakdown() -> None:
    """THE SEAM THAT SILENTLY DROPS DATA. A column written by the orchestrator and not selected
    here is invisible to the console, and nothing fails — which is exactly what happened to
    ``detail``: it has been populated for blocked and failed runs since slice 6 and no query
    ever asked for it.

    All three run-bearing queries are checked, because the fleet table, the tenant's run history
    and the tenant's per-monitor line each read a different one.
    """
    for name in ("_RUNS", "_TENANT_RUNS", "_TENANT_ANALYSES"):
        # NO getattr DEFAULT. A skip-if-missing made this pass vacuously against a name that
        # never existed (_TENANT_DETAIL), which is the failure mode this whole test is about.
        statement = getattr(reads, name)
        assert "refusals" in str(statement), f"{name} does not select the refusal breakdown"


def test_the_bff_owns_no_copy_of_the_reason_vocabulary() -> None:
    """The reason set belongs to synapse.core.stockout_risk. A copy here would be a second place
    to update when a refusal branch is added, and the copy that drifts is always the one nobody
    is looking at. The BFF passes the database's JSONB straight through.
    """
    import pathlib

    src = pathlib.Path(reads.__file__).parent
    for path in src.glob("*.py"):
        body = path.read_text(encoding="utf-8")
        assert "series_too_stale" not in body, (
            f"{path.name} names a RefusalReason member; the BFF must not carry the vocabulary"
        )


# ---------------------------------------------------------------------------
# The run's own timezone reaches the console (phase B1)
# ---------------------------------------------------------------------------


def test_every_run_query_selects_the_timezone() -> None:
    """THE SAME SEAM test_every_run_query_selects_the_refusal_breakdown guards, one column over.

    ``timezone`` has been on synapse.run since migration 0003 and no query ever asked for it, so
    the console had an INSTANT and no clock to read it against. Both run queries are checked
    because the fleet page and the tenant page each read a different one, and a column selected
    by only one of them is a screen that renders times on one page and not the other.
    """
    for name in ("_RUNS", "_TENANT_RUNS"):
        statement = getattr(reads, name)
        assert "r.timezone" in str(statement), f"{name} does not select the run's timezone"


def test_the_row_type_carries_a_non_optional_timezone() -> None:
    """NOT OPTIONAL, unlike refusals, and the asymmetry is deliberate. refusals is optional
    because a row may predate migration 0005; timezone cannot be, because 0003 CREATED the table
    with the column NOT NULL and ck_run_timezone_present also forbids the empty string. Typing it
    optional would invite a null branch that no stored row can reach.
    """
    from typing import get_type_hints

    hints = get_type_hints(reads.RunRow)
    assert "timezone" in hints, "RunRow does not carry the run's timezone"
    assert hints["timezone"] is str, "RunRow.timezone must be a plain str, not optional"


def test_the_run_row_holds_no_tenant_forbidden_field() -> None:
    """RunRow's shape against the recorded tenant-facing constraint.

    /runs is PLATFORM-only today, so this is not the constraint biting yet; it is the check that
    a WIDENED run row cannot drift into carrying an identifier that the 8b tenant view would then
    have to strip. Asserted against tenant_view_contract's exported set rather than a restated
    list, for the reason that module gives: a restated list is a second source of truth.
    """
    from typing import get_type_hints

    from synapse_ui_server.tenant_view_contract import FORBIDDEN_TENANT_FIELDS

    leaked = FORBIDDEN_TENANT_FIELDS & set(get_type_hints(reads.RunRow))
    assert not leaked, f"RunRow carries tenant-forbidden field(s): {sorted(leaked)}"


def test_the_row_types_carry_refusals_as_an_optional_mapping() -> None:
    """None and {} must stay distinguishable all the way to the client: None means the run never
    reached its plan, {} means it ran and refused nothing. A non-optional type would force one
    into the other."""
    from typing import get_type_hints

    for row_type in (reads.RunRow, reads.AnalysisState):
        hints = get_type_hints(row_type)
        assert "refusals" in hints, f"{row_type.__name__} does not carry refusals"
        assert "NoneType" in str(hints["refusals"]) or "None" in str(hints["refusals"]), (
            f"{row_type.__name__}.refusals must be optional so null stays distinct from {{}}"
        )
