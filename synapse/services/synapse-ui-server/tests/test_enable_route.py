"""The enable endpoint: three states, three answers, and one of them is the whole slice.

WHY THIS FILE EXISTS SEPARATELY FROM test_provision.py. That file tests the write module, which
cannot see whether a pair is already provisioned: the synapse_provisioner credential holds no
SELECT on the table it writes. The three-state decision therefore lives in the ROUTE, on the
reader, and it is the thing most likely to be got wrong under time pressure, because the wrong
version is shorter and passes every test that only checks the happy path.

THE WRONG VERSION, WRITTEN OUT SO IT IS RECOGNISABLE. Ask "is it in detail.analyses"; if not,
enable. That treats DISABLED as NEVER PROVISIONED, sends the insert, gets ON CONFLICT DO NOTHING,
receives no error, and answers 201. The page then re-renders from the reader still showing the
monitor off. A control that reports success and changes nothing is worse than a dead control: a
dead control is visibly inert, and this one makes the console look broken while behaving exactly
as designed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from synapse_ui_server import main as main_module
from synapse_ui_server import provision as provision_module
from synapse_ui_server import reads
from synapse_ui_server.auth import Identity, UserType
from synapse_ui_server.cm_permissions import require_tenant_configure
from synapse_ui_server.config import Config
from synapse_ui_server.main import create_app
from synapse_ui_server.provision import EnablementRefusedError, EnableOutcome

TENANT = UUID("019fb16b-e402-7dce-b026-6fa9f4919242")
OPERATOR = Identity(subject="auth0|operator", user_type=UserType.PLATFORM, tenant_id=None)

_CONFIG = Config(
    reader_url="postgresql+psycopg://r@h/d",
    lifecycle_url="postgresql+psycopg://l@h/d",
    provision_url="postgresql+psycopg://p@h/d",
    cm_api_base_url="https://cm.example",
    jwt_issuer="https://x/",
    jwt_audience="a",
    expected_database="thalamus",
)


def _detail(*, analyses: tuple[Any, ...] = (), disabled: tuple[Any, ...] = ()) -> reads.TenantDetail:
    return reads.TenantDetail(
        tenant_id=TENANT,
        name="TestCo",
        products=15,
        stores=2,
        sales_seen=400,
        latest_sale=None,
        actions_recorded=0,
        open_alerts=0,
        analyses=analyses,
        disabled_analyses=disabled,
    )


def _active(analysis_id: str) -> reads.AnalysisState:
    return reads.AnalysisState(
        analysis_id=analysis_id,
        cadence="daily",
        rung="shadow",
        timezone="Asia/Kolkata",
        enabled_at=datetime(2026, 8, 5, tzinfo=UTC),
        last_slot=None,
        last_outcome=None,
        actions_proposed=None,
        actions_appended=None,
        detail=None,
        refusals=None,
    )


def _disabled(analysis_id: str) -> reads.DisabledAnalysis:
    return reads.DisabledAnalysis(
        analysis_id=analysis_id,
        enabled_at=datetime(2026, 6, 1, tzinfo=UTC),
        disabled_at=datetime(2026, 7, 15, tzinfo=UTC),
    )


@pytest.fixture
def gated_app(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """The real app with the CM gate satisfied and both engines stubbed.

    THE GATE IS OVERRIDDEN, NOT REMOVED, and the difference is asserted in its own test below.
    Overriding lets these tests be about the three states; removing it would let a route that
    lost its gate keep passing them.
    """

    def build(
        *,
        detail: reads.TenantDetail | None,
        outcome: EnableOutcome | Exception | None = None,
    ) -> tuple[httpx.AsyncClient, list[dict[str, Any]]]:
        app = create_app(_CONFIG)
        # NO LIFESPAN, so nothing tries to open a pool. The handlers only ever pass these to the
        # two functions stubbed below, which ignore them.
        app.state.engine = object()
        app.state.provision_engine = object()
        app.dependency_overrides[require_tenant_configure] = lambda: OPERATOR

        async def fake_tenant_detail(engine: object, tenant_id: UUID) -> reads.TenantDetail | None:
            return detail

        calls: list[dict[str, Any]] = []

        async def fake_enable(engine: object, **kwargs: Any) -> EnableOutcome:
            calls.append(kwargs)
            if isinstance(outcome, Exception):
                raise outcome
            assert outcome is not None, "this test did not expect the write to be reached"
            return outcome

        monkeypatch.setattr(reads, "tenant_detail", fake_tenant_detail)
        monkeypatch.setattr(main_module, "enable_analysis", fake_enable)

        return (
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bff"),
            calls,
        )

    return build


def _url(analysis_id: str = "dead_stock") -> str:
    return f"/tenants/{TENANT}/analyses/{analysis_id}/enable"


# ---------------------------------------------------------------------------
# THE THREE STATES
# ---------------------------------------------------------------------------


async def test_never_provisioned_enables(gated_app) -> None:  # type: ignore[no-untyped-def]
    """THE HAPPY PATH, and the baseline every refusal below needs."""
    client, calls = gated_app(
        detail=_detail(),
        outcome=EnableOutcome(
            analysis_id="dead_stock", tenant_name="TestCo", canonical_positions=15, warning=None
        ),
    )
    async with client:
        response = await client.post(_url(), json={"timezone": "Asia/Kolkata"})

    assert response.status_code == 201
    body = response.json()
    assert body["analysis_id"] == "dead_stock"
    assert body["warning"] is None
    # THE CONFIGURATION THE OPERATOR DID NOT CHOOSE IS ECHOED, so the console can say "silent
    # mode, daily" without restating constants it cannot see.
    assert body["cadence"] == "daily"
    assert body["rung"] == "shadow"
    assert len(calls) == 1


async def test_an_already_active_pair_is_a_409_and_does_not_write(gated_app) -> None:  # type: ignore[no-untyped-def]
    """IDEMPOTENT AT THE DATABASE, REPORTED AT THE EDGE.

    ON CONFLICT DO NOTHING means a second enable changes nothing either way, so this could
    silently succeed and be harmless. It is reported instead, because a console that answers "done"
    to a request that did nothing teaches an operator to trust an answer that is not measuring
    anything, and the next case in this file is one where that habit is actively wrong.
    """
    client, calls = gated_app(detail=_detail(analyses=(_active("dead_stock"),)))
    async with client:
        response = await client.post(_url(), json={"timezone": "Asia/Kolkata"})

    assert response.status_code == 409
    assert "already enabled" in response.json()["detail"]
    assert calls == [], "the write was attempted for a pair that is already active"


async def test_a_disabled_pair_is_a_409_and_never_reaches_the_write(gated_app) -> None:  # type: ignore[no-untyped-def]
    """THE ONE THIS FILE EXISTS FOR, AND THE ONE THAT SILENTLY SUCCEEDS IF IT IS MISSED.

    A disabled pair has a row, so the write would be suppressed by ON CONFLICT DO NOTHING, return
    no error, and the endpoint would answer 201 having changed nothing. The refusal has to happen
    BEFORE the write, and it has to be distinguishable from "already enabled" because the operator
    needs different information: this one says re-enabling is deliberately unavailable and why.

    THE DATES ARE IN THE MESSAGE. The window that would be overwritten is the thing at stake, so
    naming it is what turns a refusal into an explanation.
    """
    client, calls = gated_app(detail=_detail(disabled=(_disabled("dead_stock"),)))
    async with client:
        response = await client.post(_url(), json={"timezone": "Asia/Kolkata"})

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "Re-enabling is deliberately not available" in detail
    assert "2026-06-01" in detail and "2026-07-15" in detail
    assert "denominator" in detail
    assert calls == [], (
        "the write was attempted against a disabled pair. ON CONFLICT DO NOTHING would have "
        "suppressed it and the endpoint would have reported success having changed nothing"
    )


async def test_a_disabled_pair_and_an_active_pair_answer_differently(gated_app) -> None:  # type: ignore[no-untyped-def]
    """TWO 409s ARE NOT ONE 409. Conflating them would tell an operator that a monitor somebody
    deliberately switched off is currently running, which is the opposite of true."""
    active_client, _ = gated_app(detail=_detail(analyses=(_active("dead_stock"),)))
    async with active_client:
        active = (await active_client.post(_url(), json={"timezone": "Asia/Kolkata"})).json()

    disabled_client, _ = gated_app(detail=_detail(disabled=(_disabled("dead_stock"),)))
    async with disabled_client:
        disabled = (await disabled_client.post(_url(), json={"timezone": "Asia/Kolkata"})).json()

    assert active["detail"] != disabled["detail"]
    assert "already enabled" in active["detail"]
    assert "already enabled" not in disabled["detail"]


async def test_one_analysis_disabled_does_not_block_enabling_another(gated_app) -> None:  # type: ignore[no-untyped-def]
    """THE STATE IS PER PAIR, NOT PER TENANT. Without this the tests above would pass against a
    handler that refused any tenant with any disabled monitor."""
    client, calls = gated_app(
        detail=_detail(disabled=(_disabled("dead_stock"),)),
        outcome=EnableOutcome(
            analysis_id="stockout_risk", tenant_name="TestCo", canonical_positions=15, warning=None
        ),
    )
    async with client:
        response = await client.post(_url("stockout_risk"), json={"timezone": "Asia/Kolkata"})

    assert response.status_code == 201
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# THE REFUSALS THE WRITE MODULE RAISES, AND THEIR STATUS CODES
# ---------------------------------------------------------------------------


async def test_an_unknown_tenant_is_404_before_anything_is_written(gated_app) -> None:  # type: ignore[no-untyped-def]
    """The reader answers None, matching every other tenant-scoped route here. 404 rather than an
    empty shell: a mistyped id rendering zeros is indistinguishable from a real tenant with
    nothing on, and this project has already paid for that confusion once."""
    client, calls = gated_app(detail=None)
    async with client:
        response = await client.post(_url(), json={"timezone": "Asia/Kolkata"})

    assert response.status_code == 404
    assert "identity_mirror.tenants" in response.json()["detail"]
    assert calls == []


async def test_an_undeclared_analysis_is_404(gated_app) -> None:  # type: ignore[no-untyped-def]
    """404 RATHER THAN 422, because the id is a path segment naming a resource that does not
    exist. A client that reached it from the registry catalogue cannot produce this."""
    client, _ = gated_app(
        detail=_detail(),
        outcome=EnablementRefusedError("not declared", reason="unknown_analysis"),
    )
    async with client:
        response = await client.post(_url("dead_stcok"), json={"timezone": "Asia/Kolkata"})

    assert response.status_code == 404


async def test_an_unresolvable_timezone_is_422_carrying_the_message(gated_app) -> None:  # type: ignore[no-untyped-def]
    """422: the request was understood and refused. THE MESSAGE IS THE PAYLOAD, because for a
    timezone it is the trigger's own sentence naming the value and the consequence, and the zone
    cannot be changed after the fact."""
    client, _ = gated_app(
        detail=_detail(),
        outcome=EnablementRefusedError(
            'synapse.provision.timezone "Mars/Olympus_Mons" does not resolve. Every slot ...',
            reason="bad_timezone",
        ),
    )
    async with client:
        response = await client.post(_url(), json={"timezone": "Mars/Olympus_Mons"})

    assert response.status_code == 422
    assert "does not resolve" in response.json()["detail"]


async def test_a_reason_with_no_status_mapping_is_not_silently_a_422(gated_app) -> None:  # type: ignore[no-untyped-def]
    """THE MAPPING HAS NO FALLBACK, DELIBERATELY.

    A `.get(reason, 422)` would file a future refusal under "the request was malformed" without
    anybody deciding that, and a wrong status on a write path is how a client learns to retry
    something it should not. An unmapped reason raises instead, which is loud.
    """
    client, _ = gated_app(
        detail=_detail(),
        outcome=EnablementRefusedError("something new", reason="not_yet_mapped"),
    )
    with pytest.raises(KeyError):
        async with client:
            await client.post(_url(), json={"timezone": "Asia/Kolkata"})


# ---------------------------------------------------------------------------
# WHAT THE ROUTE PASSES DOWN, AND WHAT IT REFUSES TO ACCEPT
# ---------------------------------------------------------------------------


async def test_cadence_and_rung_in_the_body_are_ignored_not_honoured(gated_app) -> None:  # type: ignore[no-untyped-def]
    """A HAND-MADE REQUEST IS THE THREAT MODEL HERE, not the console.

    The console cannot send these, but the endpoint is reachable by anything holding a PLATFORM
    token and the permission. Pydantic drops unknown fields by default, so this asserts the
    DEFAULT still holds rather than assuming it: a model_config with extra="allow" added later for
    an unrelated reason would make a posted rung reach the write.

    THE BLAST RADIUS IS THE FLEET. One provision naming a rung above its analysis's max_rung stops
    the 04:00 sweep for every tenant, not just this one.
    """
    client, calls = gated_app(
        detail=_detail(),
        outcome=EnableOutcome(
            analysis_id="dead_stock", tenant_name="TestCo", canonical_positions=15, warning=None
        ),
    )
    async with client:
        response = await client.post(
            _url(),
            json={"timezone": "Asia/Kolkata", "rung": "suggest", "cadence": "hourly"},
        )

    assert response.status_code == 201
    assert set(calls[0]) == {"tenant_id", "analysis_id", "timezone", "enabled_at"}, (
        f"the route passed something it should not have: {sorted(calls[0])}"
    )
    assert calls[0]["timezone"] == "Asia/Kolkata"


async def test_the_warning_is_returned_and_is_not_an_error(gated_app) -> None:  # type: ignore[no-untyped-def]
    """A tenant with no canonical positions IS enabled. 201, with the warning in the body, because
    enabling ahead of ingestion is legitimate and a week of empty runs otherwise reads as a broken
    monitor. This is NIBPL in staging."""
    client, _ = gated_app(
        detail=_detail(),
        outcome=EnableOutcome(
            analysis_id="dead_stock",
            tenant_name="NIBPL",
            canonical_positions=0,
            warning='"NIBPL" has no canonical positions. Enabled anyway ...',
        ),
    )
    async with client:
        response = await client.post(_url(), json={"timezone": "Asia/Kolkata"})

    assert response.status_code == 201
    assert "no canonical positions" in response.json()["warning"]


# ---------------------------------------------------------------------------
# THE GATE IS ON THE ROUTE
# ---------------------------------------------------------------------------


def test_the_enable_route_is_gated_on_the_cm_permission() -> None:
    """THE OVERRIDE IN EVERY TEST ABOVE IS ONLY SAFE IF THIS PASSES.

    Every test in this file replaces require_tenant_configure with a function that returns an
    operator, which is exactly what a route that had LOST its gate would look like from the
    inside. This reads the dependency off the registered route instead, so the two cannot both be
    wrong in the same direction.

    ASSERTED AGAINST THE OTHER ROUTES TOO. The gate belongs on this one and must not spread: every
    read stays on require_platform alone, which is the one-discriminator rule auth.py states.
    """
    app = create_app(_CONFIG)
    enable = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/tenants/{tenant_id}/analyses/{analysis_id}/enable"
    )
    gated_by = {
        dependency.call
        for dependency in enable.dependant.dependencies  # type: ignore[attr-defined]
    }
    assert require_tenant_configure in gated_by, (
        "the enable route is not gated on the Customer Master permission"
    )

    for route in app.routes:
        path = getattr(route, "path", "")
        if path in ("/healthz", "/readyz") or not hasattr(route, "dependant"):
            continue
        if path.endswith("/enable"):
            continue
        others = {d.call for d in route.dependant.dependencies}
        assert require_tenant_configure not in others, (
            f"{path} acquired the provisioning permission gate; it belongs on the write alone"
        )


def test_the_route_logs_the_actor_and_the_configuration() -> None:
    """THE AUDIT RECORD FOR 5e IS A LOG LINE, AND ITS FIELDS ARE THE RECORD.

    synapse.provision stores enabled_at and stores NOBODY, so this line is the only thing that
    connects the change to a person. Asserted on the source because the alternative is a caplog
    test that passes while the field names drift.

    THIS IS NOT ENOUGH AND THE MODULE SAYS SO. Cloud Logging's retention is the ceiling and
    nothing can answer "who enabled this monitor" from the database at all. The real home is
    synapse.provision_events, deferred behind the first disable because it is the append-only
    enablement history in disguise. Until it exists, 5e must not reach a production tenant.
    """
    from pathlib import Path

    source = Path(main_module.__file__).read_text(encoding="utf-8")
    for field in (
        '"actor_subject": identity.subject',
        '"tenant_id": str(tenant_id)',
        '"analysis_id": outcome.analysis_id',
        '"timezone": body.timezone',
        # Cloud Logging files anything without `severity` at DEFAULT, where no alert can match it.
        '"severity": "NOTICE"',
    ):
        assert field in source, f"the provisioning audit line no longer carries {field}"

    assert "must not reach a production tenant" in source, (
        "the standing condition on the log-line-instead-of-a-table decision was removed"
    )


def test_the_route_offers_no_disable_or_re_enable() -> None:
    """THE THIRD LAYER. No function in provision.py, no UPDATE in the grant, and no route here."""
    app = create_app(_CONFIG)
    paths = {
        (getattr(route, "path", ""), method)
        for route in app.routes
        for method in (getattr(route, "methods", None) or set())
    }
    for path, method in paths:
        assert "disable" not in path, f"a disable route exists: {method} {path}"
        assert method not in ("DELETE", "PUT", "PATCH"), (
            f"{method} {path} exists. Nothing in this console edits or removes a provision"
        )


def test_provision_module_is_the_one_the_route_calls() -> None:
    """A VACUITY GUARD FOR THE STUBS ABOVE. Every test in this file monkeypatches
    main_module.enable_analysis; if main.py stopped importing it by that name the patch would
    silently attach to nothing and the assertions about `calls` would be vacuous."""
    assert main_module.enable_analysis is provision_module.enable_analysis
