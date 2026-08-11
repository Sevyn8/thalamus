"""/tenants/{id}/alerts and /tenants/{id}/alerts/{event_id} — the first per-ACTION reads here.

WHAT THESE ADDED AND WHY IT IS TWO ENDPOINTS. Every earlier read counts actions; `synapse.actions`
appeared in this service only as `count(*)` subqueries. So the console had never shown an
individual alert, and the tenant page's Alerts section aggregated per MONITOR — "3 alerts raised"
with nothing to open. A detail page needs a row to click FROM as well as one to click TO.

THE NEGATIVE TEST IS THE REQUIRED ONE and it is at the bottom of this file. These payloads carry
sku_id, product_name and store_name — every one in tenant_view_contract.FORBIDDEN_TENANT_FIELDS.
The contract's whole argument is that a rendered-but-hidden field is still a leak, so "do not
reuse this on the tenant view" has to be a property rather than a note.

NO DATABASE. The reader is driven through a recording fake so the SQL, the session scope and the
404 semantics are all asserted offline; the RLS behaviour the fake stands in for is what the
integration suite covers.
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
OTHER_TENANT = UUID("decafbad-0000-4000-8000-000000000001")
EVENT = UUID("019fb16b-0000-7000-8000-00000000ab01")
STORE = UUID("019fb16b-0000-7000-8000-00000000cd02")


def _engine() -> AsyncEngine:
    """A sentinel where an engine is expected, typed so mypy --strict accepts the call.

    Never touched: every test patches rls_platform_session, which is the only thing that would
    open a connection. A real engine would make a passing test consistent with one having been
    opened, which is the opposite of what these prove.
    """
    return cast("AsyncEngine", object())


def _alert(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "event_id": EVENT,
        "as_of": date(2026, 8, 6),
        "recorded_at": datetime(2026, 8, 6, 3, 1, tzinfo=UTC),
        "declaration_id": "dead_stock",
        "declaration_version": "0.1.0",
        "verb": "review",
        "arm": "treatment",
        "expires_on": date(2026, 9, 5),
        "quantity_at_stake": Decimal("40.000"),
        "days_since_last_sale": 214,
        "days_of_cover": None,
        "thresholds": {"stale_after_days": 90, "expires_after_days": 30},
        "target": {"tenant_id": str(TENANT), "store_id": str(STORE), "sku_id": "SKU-000123"},
        "store_id": STORE,
        "sku_id": "SKU-000123",
        "store_name": "Mokotow",
        "product_name": "Vitamin C 500mg",
        "current_stock_qty": Decimal("38.000"),
        # No operator has acted on this target: the "open" state (slice 5d).
        "lifecycle_verb": None,
        "lifecycle_reason": None,
        "lifecycle_snoozed_until": None,
        "lifecycle_recorded_at": None,
        "lifecycle_actor": None,
        # B2a widened _ALERT_COLUMNS with the SERVER-DERIVED state, so this fixture carries the
        # new row shape. The 5c page's BEHAVIOUR is unchanged: it renders the state it is given
        # rather than deriving one, and for an untouched target that state is 'open' either way.
        "lifecycle_state": "open",
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

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _RecordingConn:
    """Answers from a script and records every (statement, params) pair."""

    def __init__(
        self,
        *,
        exists: bool = True,
        detail: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        listing: list[dict[str, Any]] | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._exists = exists
        self._detail = detail if detail is not None else [_alert()]
        self._history = history or []
        self._listing = listing if listing is not None else [_alert()]

    async def execute(self, statement: object, params: dict[str, Any]) -> _FakeResult:
        sql = str(statement)
        self.calls.append((sql, params))
        if "identity_mirror.tenants WHERE tenant_id" in sql:
            return _FakeResult([{"?column?": 1}] if self._exists else [])
        if "FROM synapse.actions h" in sql:
            return _FakeResult(self._history)
        if "a.event_id = CAST(:event AS uuid)" in sql:
            return _FakeResult(self._detail)
        return _FakeResult(self._listing)


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Swap rls_platform_session for one yielding a recording connection.

    PATCHED AT THE MODULE, so reads.py's own call site is the one under test. A test that patched
    elsewhere could pass while reads.py opened a raw connection — which against FORCE ROW LEVEL
    SECURITY returns zero rows and raises nothing.
    """

    def install(conn: _RecordingConn) -> None:
        @asynccontextmanager
        async def fake(engine: object, tenant: object):  # type: ignore[no-untyped-def]
            conn.opened_with = (engine, tenant)  # type: ignore[attr-defined]
            yield conn

        monkeypatch.setattr(reads, "rls_platform_session", fake)

    return install


# ---------------------------------------------------------------------------
# The SQL
# ---------------------------------------------------------------------------


def test_the_detail_query_is_scoped_by_both_tenant_and_event() -> None:
    """BOTH PREDICATES IN ONE WHERE. This is what makes a tenant mismatch return no row rather
    than someone else's alert, and what makes the 404 honest instead of a filtered 403."""
    sql = str(reads._ALERT_DETAIL)
    assert "a.tenant_id = CAST(:tenant AS uuid)" in sql
    assert "a.event_id = CAST(:event AS uuid)" in sql


def test_both_display_joins_are_left_joins() -> None:
    """synapse.actions carries no FK into any DIS schema — an append-only log outlives what it
    references. An INNER join would silently drop the alert for a delisted SKU or a closed store,
    which is exactly when someone is looking at it."""
    for statement in (reads._ALERT_DETAIL, reads._TENANT_ALERTS):
        sql = str(statement)
        # Three now: the two display joins plus the lifecycle LATERAL added in 5d. Counted
        # rather than merely present, so an INNER creeping in anywhere fails here.
        assert sql.count("LEFT JOIN") == 3, sql
        assert "JOIN identity_mirror.stores" in sql
        assert "JOIN canonical.store_sku_current_position" in sql
        assert "LEFT JOIN LATERAL" in sql


def test_the_alert_queries_touch_no_canonical_table_beyond_the_position() -> None:
    """THE APPROVED CANONICAL SURFACE, pinned. The position join is the only canonical read this
    slice was given; a per-render scan of sale events for copy garnish was ruled out at the gate.
    """
    for statement in (reads._ALERT_DETAIL, reads._TENANT_ALERTS, reads._ALERT_HISTORY):
        sql = str(statement)
        assert "store_sku_sale_events" not in sql
        assert "daily_series" not in sql


def test_history_groups_on_the_whole_target_not_the_projections() -> None:
    """target IS the grain the idempotency index uses (declaration_id, declaration_version, verb,
    as_of, target, payload_hash). Matching on store_id/sku_id instead would silently regroup an
    analysis declared at a different grain."""
    sql = str(reads._ALERT_HISTORY)
    assert "a.target = h.target" in sql
    assert "a.declaration_id = h.declaration_id" in sql


def test_history_is_ordered_newest_first_and_keyed_on_the_event() -> None:
    """One slot can hold TWO rows: payload_hash is in the idempotency index, so a payload that
    changed within a slot writes a second row. Collapsing on as_of would hide it."""
    sql = str(reads._ALERT_HISTORY)
    assert "ORDER BY h.as_of DESC" in sql
    assert "h.event_id" in sql


# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------


async def test_the_detail_reads_under_the_platform_session(patched) -> None:  # type: ignore[no-untyped-def]
    """synapse.actions is FORCE ROW LEVEL SECURITY: a session without app.user_type matches ZERO
    rows and raises nothing, so "which session" decides whether this endpoint works at all."""
    conn = _RecordingConn()
    patched(conn)
    await reads.alert_detail(_engine(), TENANT, EVENT)
    assert conn.opened_with[1] is None, "the session must be PLATFORM (tenant=None)"  # type: ignore[attr-defined]


async def test_the_detail_returns_the_alert_and_its_history(patched) -> None:  # type: ignore[no-untyped-def]
    conn = _RecordingConn(
        history=[
            {
                "event_id": UUID(int=7),
                "as_of": date(2026, 8, 5),
                "recorded_at": datetime(2026, 8, 5, 3, 1, tzinfo=UTC),
                "quantity_at_stake": Decimal("40.000"),
                "days_since_last_sale": 213,
                "days_of_cover": None,
            }
        ]
    )
    patched(conn)

    detail = await reads.alert_detail(_engine(), TENANT, EVENT)

    assert detail is not None
    assert detail.alert.event_id == EVENT
    assert detail.alert.sku_id == "SKU-000123"
    assert detail.alert.days_since_last_sale == 214
    assert detail.alert.thresholds == {"stale_after_days": 90, "expires_after_days": 30}
    assert len(detail.history) == 1
    assert detail.history[0].as_of == date(2026, 8, 5)


async def test_the_two_quantities_are_carried_separately(patched) -> None:  # type: ignore[no-untyped-def]
    """AT DETECTION vs CURRENT. quantity_at_stake is frozen on the row; current_stock_qty comes
    from today's position. A recovered position must be able to read as recovered, which is only
    possible if the two survive as different fields."""
    conn = _RecordingConn(
        detail=[_alert(quantity_at_stake=Decimal("40.000"), current_stock_qty=Decimal("0.000"))]
    )
    patched(conn)

    detail = await reads.alert_detail(_engine(), TENANT, EVENT)

    assert detail is not None
    assert detail.alert.quantity_at_stake == Decimal("40.000")
    assert detail.alert.current_stock_qty == Decimal("0.000")


async def test_an_unknown_event_returns_none_and_skips_the_history_query(patched) -> None:  # type: ignore[no-untyped-def]
    """None is what the route turns into a 404, and the history must not run for a row that does
    not exist."""
    conn = _RecordingConn(detail=[])
    patched(conn)

    assert await reads.alert_detail(_engine(), TENANT, EVENT) is None
    assert not [c for c in conn.calls if "FROM synapse.actions h" in c[0]]


async def test_a_tenant_mismatch_is_the_same_answer_as_a_typo(patched) -> None:  # type: ignore[no-untyped-def]
    """THE 404-NOT-403 DECISION, asserted on behaviour. The reader cannot distinguish the two
    because both predicates are in one WHERE — so there is no branch that could leak "this event
    exists, just not here"."""
    conn = _RecordingConn(detail=[])
    patched(conn)

    assert await reads.alert_detail(_engine(), OTHER_TENANT, EVENT) is None
    detail_calls = [c for c in conn.calls if "a.event_id = CAST(:event AS uuid)" in c[0]]
    assert detail_calls[0][1] == {"tenant": str(OTHER_TENANT), "event": str(EVENT)}


async def test_the_listing_returns_none_for_an_unknown_tenant(patched) -> None:  # type: ignore[no-untyped-def]
    """An empty list for a mistyped id is indistinguishable from a real tenant that has never
    been alerted — the same reason /tenants/{id}/runs probes first."""
    conn = _RecordingConn(exists=False)
    patched(conn)

    assert await reads.tenant_alerts(_engine(), TENANT) is None
    assert not [c for c in conn.calls if "FROM synapse.actions a" in c[0]]


@pytest.mark.parametrize(("asked", "expected"), [(10, 10), (500, 500), (501, 500), (0, 1), (-5, 1)])
async def test_the_listing_limit_is_bounded_both_ends(patched, asked: int, expected: int) -> None:  # type: ignore[no-untyped-def]
    conn = _RecordingConn()
    patched(conn)
    await reads.tenant_alerts(_engine(), TENANT, limit=asked)
    listing = [c for c in conn.calls if "ORDER BY a.as_of DESC" in c[0]]
    assert listing[0][1]["limit"] == expected


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------


def _client(monkeypatch: pytest.MonkeyPatch, *, listing: object, detail: object) -> Any:
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

    async def _alerts(engine: object, tenant_id: UUID, *, limit: int = 100) -> object:
        return listing

    async def _detail(engine: object, tenant_id: UUID, event_id: UUID, **kw: object) -> object:
        return detail

    monkeypatch.setattr(reads, "tenant_alerts", _alerts)
    monkeypatch.setattr(reads, "alert_detail", _detail)
    app.dependency_overrides[require_platform] = lambda: Identity(
        subject="s", user_type=UserType.PLATFORM, tenant_id=None
    )
    app.state.engine = object()
    return TestClient(app)


def test_the_detail_route_404s_for_an_unknown_or_mismatched_event(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch, listing=(), detail=None)
    response = client.get(f"/tenants/{TENANT}/alerts/{EVENT}")
    assert response.status_code == 404
    assert str(EVENT) in response.json()["detail"]


def test_the_listing_route_404s_for_an_unknown_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch, listing=None, detail=None)
    assert client.get(f"/tenants/{TENANT}/alerts").status_code == 404


def test_the_detail_route_returns_the_alert_and_history(monkeypatch: pytest.MonkeyPatch) -> None:
    alert = reads.AlertRow(**{k: v for k, v in _alert().items()})
    detail = reads.AlertDetail(alert=alert, history=())
    client = _client(monkeypatch, listing=(), detail=detail)

    body = client.get(f"/tenants/{TENANT}/alerts/{EVENT}").json()

    assert body["alert"]["sku_id"] == "SKU-000123"
    assert body["alert"]["thresholds"]["stale_after_days"] == 90
    assert body["history"] == []


def test_both_routes_exist_and_nest_under_the_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bare /alerts/{event_id} would be the first route here where the tenant is implicit, and
    the mismatch case would be unanswerable."""
    client = _client(monkeypatch, listing=(), detail=None)
    paths = {r.path for r in client.app.routes if hasattr(r, "path")}
    assert "/tenants/{tenant_id}/alerts" in paths
    assert "/tenants/{tenant_id}/alerts/{event_id}" in paths
    assert "/alerts/{event_id}" not in paths


# ===========================================================================================
# THE REQUIRED NEGATIVE TEST: this payload must never reach a tenant-facing surface
# ===========================================================================================
# The mirror of 8b's test, in the opposite direction. 8b's asserts that the TENANT view carries no
# per-product field; this asserts that the PLATFORM alert payload — which is made almost entirely
# of such fields — is structurally unable to be the thing a tenant view serves.
#
# WHY IT IS SHAPED THIS WAY TODAY. tenant_view_contract.TENANT_READ_MODULE names
# "synapse_ui_server.tenant", and that module DOES NOT EXIST — 8b was never built. So the
# strongest available assertions are (1) that the alert payload is positively identified as
# forbidden material, (2) that no tenant-facing surface exists at all, and (3) that if the tenant
# module ever appears it does not import this one. The third arms itself automatically.


def test_the_alert_payload_is_made_of_fields_the_tenant_contract_forbids() -> None:
    """POSITIVE IDENTIFICATION, so the ban is about THIS type rather than a general caution. If
    this ever fails, the alert row has stopped carrying per-product data and the reason for the
    prohibition has changed — which is a decision, not a green tick."""
    from synapse_ui_server.tenant_view_contract import FORBIDDEN_TENANT_FIELDS

    fields = set(reads.AlertRow.__dataclass_fields__)
    leaking = fields & FORBIDDEN_TENANT_FIELDS
    assert leaking >= {"sku_id", "store_id", "product_name", "store_name"}, (
        f"AlertRow no longer carries the per-product fields the ban exists for; found {leaking}"
    )


def test_no_tenant_facing_read_module_exists_yet() -> None:
    """The contract names the module 8b will add. While it is absent there is nothing that COULD
    reuse these reads, and this test is what turns that from an assumption into a checked fact —
    it fails the day the module appears, sending whoever adds it to the test below."""
    import importlib.util

    from synapse_ui_server.tenant_view_contract import TENANT_READ_MODULE

    assert importlib.util.find_spec(TENANT_READ_MODULE) is None, (
        f"{TENANT_READ_MODULE} now exists. Extend "
        "test_the_tenant_read_module_does_not_import_the_alert_reads to assert it does not import "
        "reads.AlertRow / alert_detail, and add the forbidden import-linter contract "
        "tenant_view_contract describes."
    )


def test_the_tenant_read_module_does_not_import_the_alert_reads() -> None:
    """Arms itself. Skips while the module is absent and becomes a real assertion the moment it
    is not — rather than being written later, by someone who has to remember this file."""
    import importlib.util

    from synapse_ui_server.tenant_view_contract import TENANT_READ_MODULE

    spec = importlib.util.find_spec(TENANT_READ_MODULE)
    if spec is None or spec.origin is None:
        pytest.skip(f"{TENANT_READ_MODULE} does not exist yet; guarded by the test above")
    body = __import__("pathlib").Path(spec.origin).read_text(encoding="utf-8")
    for banned in ("AlertRow", "AlertDetail", "alert_detail", "tenant_alerts"):
        assert banned not in body, f"{TENANT_READ_MODULE} references {banned}"


def test_every_route_in_this_service_requires_platform() -> None:
    """THE ONE THAT BITES TODAY. The alert endpoints cannot leak to a tenant because no route
    here serves a tenant: every non-health route depends on require_platform. A new route added
    without it fails here rather than at review.

    THE SEARCH IS RECURSIVE, AND SLICE 5e IS WHY. It used to read the route's TOP-LEVEL
    dependencies only, which was exactly right while every route declared
    ``Depends(require_platform)`` itself. 5e's enable route declares
    ``Depends(require_tenant_configure)``, which in turn declares ``Depends(require_platform)``,
    so the PLATFORM check still runs first and a TENANT token is still refused before anything
    else happens. A flat search would have reported that route as unguarded.

    RECURSING RATHER THAN EXEMPTING THE ROUTE, deliberately. An exemption list would make this
    test's claim smaller than its name, and the one route it exempted would be the only route in
    the service that writes a customer's configuration. Recursion keeps the claim exactly as
    stated and makes it true through composition: a route reachable without require_platform
    anywhere in its dependency tree still fails.
    """
    from fastapi.routing import APIRoute
    from synapse_ui_server.auth import require_platform
    from synapse_ui_server.config import Config
    from synapse_ui_server.main import create_app

    def gates(dependant: object) -> set[object]:
        """Every dependency on the route's tree, at any depth."""
        found: set[object] = set()
        for dependency in dependant.dependencies:  # type: ignore[attr-defined]
            found.add(dependency.call)
            found |= gates(dependency)
        return found

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
    unguarded: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.path in {"/healthz", "/readyz"}:
            continue
        if require_platform not in gates(route.dependant):
            unguarded.append(route.path)
    assert not unguarded, f"routes without require_platform: {unguarded}"
    # THE VACUITY GUARD. A `gates` that returned an empty set for everything would make the loop
    # above find nothing to complain about only if the membership test also passed, so this pins
    # that the traversal actually reaches the transitive case 5e introduced.
    enable = next(
        r for r in app.routes if isinstance(r, APIRoute) and r.path.endswith("/analyses/{analysis_id}/enable")
    )
    assert require_platform not in {d.call for d in enable.dependant.dependencies}, (
        "the enable route now declares require_platform directly; the recursion above is no "
        "longer exercised by any route and this test has stopped proving what it claims"
    )
    assert require_platform in gates(enable.dependant)
