"""GET /deliveries: the console's window onto the delivery ledger.

WHAT THIS FILE IS ABOUT AND WHAT IT IS NOT. Axon's own suite (axon/tests/test_reads.py) owns the
SQL, the session posture and the counts. This file owns the three things only the ROUTE can get
wrong: which engine it reads through, that it is PLATFORM-gated, and that one request produces
one consistent answer rather than two that can disagree.

THE ENGINE ONE IS THE POINT OF THE FILE. There are two Axon engines on app.state and they are
opposites: ``axon_engine`` is the SENDER, which holds INSERT and no SELECT anywhere, and
``axon_reader_engine`` is the READER, which holds SELECT and no write verb. Reading through the
wrong one fails in production with `permission denied for table platform_deliveries`, behind a
green deploy, on a page nobody would connect to a grant file. That is slice 5e's failure exactly,
and it is a one-word edit away at every call site.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from synapse_ui_server import main as main_module
from synapse_ui_server.auth import Identity, UserType, require_platform
from synapse_ui_server.config import Config
from synapse_ui_server.main import create_app

TENANT = UUID("019fb16b-e402-7dce-b026-6fa9f4919242")
DELIVERY = UUID("019f9d6d-c032-7e03-a232-ee77299f9b5d")
OPERATOR = Identity(subject="auth0|operator", user_type=UserType.PLATFORM, tenant_id=None)

_CONFIG = Config(
    reader_url="postgresql+psycopg://r@h/d",
    lifecycle_url="postgresql+psycopg://l@h/d",
    provision_url="postgresql+psycopg://p@h/d",
    cm_api_base_url="https://cm.example",
    jwt_issuer="https://x/",
    jwt_audience="a",
    expected_database="thalamus",
    axon_reader_url="postgresql+psycopg://ar@h/d",
    axon_project_id="test-project",
    axon_platform_oncall_email="oncall@test.invalid",
)

# DISTINGUISHABLE SENTINELS, which is the whole mechanism of the engine test below. Two bare
# object() instances would also be distinguishable, but a failure would print two addresses; these
# print what was reached instead.
_SENDER_ENGINE = "SENDER-ENGINE-insert-only-no-select"
_READER_ENGINE = "READER-ENGINE-select-only-no-write"


class _Row:
    """Stands in for axon.reads.DeliveryRow. The route serialises ``row.__dict__``, so anything
    with the right attributes is enough; Axon's suite owns the real mapping."""

    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


def _row(**overrides: Any) -> _Row:
    fields: dict[str, Any] = {
        "scope": "PLATFORM",
        "delivery_id": DELIVERY,
        "tenant_id": None,
        "created_at": datetime(2026, 8, 11, 6, 17, 8, tzinfo=UTC),
        "channel": "email",
        "notification_class": "synapse.provision.enabled",
        "subject_kind": "synapse.provision",
        "subject_id": "019f9d6d-c032-7e03-a232-ee77299f9b5d:stockout_risk",
        "recipient": "oncall@sevyn8.example",
        "state": "accepted",
        "suppression_reason": None,
        "provider": "sendgrid",
        "failure_detail": None,
        "actor_subject": "auth0|operator",
    }
    fields.update(overrides)
    return _Row(**fields)


class _Counts:
    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


def _counts(**overrides: Any) -> _Counts:
    fields: dict[str, Any] = {
        "total": 1,
        "accepted": 1,
        "failed": 0,
        "suppressed": 0,
        "suppressed_not_onboarded": 0,
    }
    fields.update(overrides)
    return _Counts(**fields)


@pytest.fixture
def gated_app(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """The real app with both readers stubbed AT main_module, and the engines set to sentinels.

    PATCHED AT main_module, NOT AT axon.reads, and this suite already names the trap twice: a stub
    installed on the other name would pass against a route that had stopped calling it.
    """

    def build(
        *,
        rows: list[_Row] | None = None,
        truncated: bool = False,
        counts: _Counts | None = None,
    ) -> tuple[httpx.AsyncClient, list[Any], list[Any]]:
        app = create_app(_CONFIG)
        # NO LIFESPAN, so nothing opens a pool. The route only ever passes these through to the
        # two stubs below, which record and ignore them.
        app.state.axon_engine = _SENDER_ENGINE
        app.state.axon_reader_engine = _READER_ENGINE

        list_engines: list[Any] = []
        counts_engines: list[Any] = []

        async def fake_recent(engine: Any) -> tuple[tuple[_Row, ...], bool]:
            list_engines.append(engine)
            return tuple(rows if rows is not None else [_row()]), truncated

        async def fake_counts(engine: Any) -> _Counts:
            counts_engines.append(engine)
            return counts if counts is not None else _counts()

        monkeypatch.setattr(main_module, "recent_deliveries", fake_recent)
        monkeypatch.setattr(main_module, "delivery_counts", fake_counts)
        app.dependency_overrides[require_platform] = lambda: OPERATOR

        transport = httpx.ASGITransport(app=app)
        return (
            httpx.AsyncClient(transport=transport, base_url="http://test"),
            list_engines,
            counts_engines,
        )

    return build


# ---------------------------------------------------------------------------
# THE ENGINE. The reason this file exists.
# ---------------------------------------------------------------------------


async def test_both_reads_go_through_the_reader_engine(gated_app: Any) -> None:
    """NOT THE SENDER'S. axon_sender holds INSERT and NO SELECT ANYWHERE, deliberately, so a read
    issued through it fails in production with `permission denied for table platform_deliveries`
    behind a green deploy. That is slice 5e's failure, and both engines are on app.state one
    attribute name apart.

    ASSERTED ON BOTH CALLS, not just the list. The counts are a second statement and would be a
    second place to reach the wrong credential.
    """
    client, list_engines, counts_engines = gated_app()
    async with client:
        response = await client.get("/deliveries")

    assert response.status_code == 200
    assert list_engines == [_READER_ENGINE]
    assert counts_engines == [_READER_ENGINE]


async def test_the_route_never_touches_the_sender_engine(gated_app: Any) -> None:
    """THE SAME CLAIM STATED AS AN ABSENCE, because the test above would still pass if the route
    somehow reached both. The read path has no business holding a write credential at all."""
    client, list_engines, counts_engines = gated_app()
    async with client:
        await client.get("/deliveries")

    assert _SENDER_ENGINE not in list_engines + counts_engines


# ---------------------------------------------------------------------------
# THE GATE
# ---------------------------------------------------------------------------


def test_the_route_is_platform_gated() -> None:
    """THE OVERRIDE IN EVERY TEST ABOVE IS ONLY SAFE IF THIS PASSES.

    Every test in this file replaces require_platform with a function returning an operator, which
    is exactly what a route that had LOST its gate would look like from the inside. This reads the
    dependency off the REGISTERED ROUTE instead, so the two cannot both be wrong in the same
    direction. Same device, same reason, as test_enable_route's gate assertion.

    THE LEDGER IS FLEET-WIDE AND THERE IS NO BACKSTOP BEHIND THIS CHECK. One page carries who was
    contacted, at what address, about which tenant's monitor, and the read runs under
    rls_platform_session, which sees every tenant. A missing gate here is a cross-tenant
    disclosure, not a missing filter.
    """
    app = create_app(_CONFIG)
    route = next(r for r in app.routes if getattr(r, "path", None) == "/deliveries")
    gated_by = {
        dependency.call
        for dependency in route.dependant.dependencies  # type: ignore[attr-defined]
    }
    assert require_platform in gated_by, "GET /deliveries is not PLATFORM-gated"


# ---------------------------------------------------------------------------
# THE ANSWER
# ---------------------------------------------------------------------------


async def test_one_request_returns_the_rows_and_the_counts_together(gated_app: Any) -> None:
    """ONE ROUTE, NOT TWO, AND THIS PINS THE DEPARTURE FROM /alerts AND /alerts/state-counts.

    Those are split because the chips are filter CONTROLS, read once while the list refetches
    under them. Here the cards and the list are one screenshot of one moment, always rendered
    together. Two routes would be two round trips that can disagree, and a card that disagrees
    with the rows beneath it reads as a broken count rather than as a race.
    """
    client, _, _ = gated_app(
        rows=[_row(), _row(state="failed", failure_detail="SendGrid returned 403")],
        counts=_counts(total=2, accepted=1, failed=1),
    )
    async with client:
        body = (await client.get("/deliveries")).json()

    assert len(body["deliveries"]) == 2
    assert body["counts"] == {
        "total": 2,
        "accepted": 1,
        "failed": 1,
        "suppressed": 0,
        "suppressed_not_onboarded": 0,
    }


async def test_the_truncation_flag_reaches_the_response(gated_app: Any) -> None:
    """A capped list that does not SAY it is capped is a page presenting a floor as a total. The
    flag is computed in Axon and has to survive the route to be worth computing."""
    client, _, _ = gated_app(truncated=True)
    async with client:
        assert (await client.get("/deliveries")).json()["truncated"] is True

    client, _, _ = gated_app(truncated=False)
    async with client:
        assert (await client.get("/deliveries")).json()["truncated"] is False


async def test_an_empty_ledger_is_a_normal_answer(gated_app: Any) -> None:
    """NO 404, NO ERROR. There is no id here whose absence means the caller asked for something
    that does not exist. The console renders its own empty state."""
    client, _, _ = gated_app(rows=[], counts=_counts(total=0, accepted=0))
    async with client:
        response = await client.get("/deliveries")

    assert response.status_code == 200
    assert response.json()["deliveries"] == []
    assert response.json()["counts"]["total"] == 0


async def test_a_tenant_row_serialises_with_its_scope_and_tenant_id(gated_app: Any) -> None:
    """THE HALF OF THE UNION THAT CANNOT EXIST YET, exercised through the stub because it cannot
    be exercised through the database. This asserts the ROUTE serialises a tenant row, which is a
    different and weaker claim than asserting one comes back, and it is the honest one today."""
    client, _, _ = gated_app(rows=[_row(scope="TENANT", tenant_id=TENANT, channel="whatsapp")])
    async with client:
        row = (await client.get("/deliveries")).json()["deliveries"][0]

    assert row["scope"] == "TENANT"
    assert row["tenant_id"] == str(TENANT)
    assert row["channel"] == "whatsapp"


async def test_the_response_carries_no_field_claiming_delivery(gated_app: Any) -> None:
    """ACCEPTED IS NOT DELIVERED, ENFORCED ON THE WIRE.

    A row records what a provider answered at the moment of sending. Whether the message arrived
    is knowable only from an inbound receipt and that plane does not exist. A field named `sent`
    or `delivered` would make every reader of this API believe something the platform cannot
    observe, and an API field outlives the copy on any one page.
    """
    client, _, _ = gated_app()
    async with client:
        body = (await client.get("/deliveries")).json()

    serialised = str(body).lower()
    assert "accepted" in serialised
    for word in ("delivered", '"sent"', "'sent'"):
        assert word not in serialised, f"the delivery response asserts {word}, which it cannot observe"
