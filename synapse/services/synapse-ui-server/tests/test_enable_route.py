"""The enable endpoint: three states, three answers, and one of them is the whole slice.

WHY THIS FILE EXISTS SEPARATELY FROM test_provision.py. That file tests the write module, which
cannot see whether a pair is already provisioned: the synapse_provisioner credential holds no
SELECT on the table it writes. The three-state decision therefore lives in the ROUTE, on the
reader, and it is the thing most likely to be got wrong under time pressure, because the wrong
version is shorter and passes every test that only checks the happy path.

THE WRONG VERSION, WRITTEN OUT SO IT IS RECOGNISABLE. Ask "is it in detail.analyses"; if not,
enable. That treats DISABLED as NEVER PROVISIONED and sends the insert at a pair that already has
a row. The database refuses it on pk_provision, and all the write module can then say is "a row
already existed": it holds no SELECT there, so it cannot tell the operator that the monitor was
deliberately switched off, when it was, or that re-enabling is unavailable by design. The reader
had every one of those facts before the request was sent. A console that offers an action the
database will refuse, for a reason it could have explained first, is worse than a dead control:
a dead control is visibly inert, and this one makes the console look broken while behaving
exactly as designed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from axon import TOPIC_SEND_REQUESTED, Channel, SendRequested
from synapse_ui_server import main as main_module
from synapse_ui_server import provision as provision_module
from synapse_ui_server import reads
from synapse_ui_server.auth import Identity, UserType, require_platform
from synapse_ui_server.cm_permissions import require_tenant_configure
from synapse_ui_server.config import Config
from synapse_ui_server.main import create_app
from synapse_ui_server.provision import EnablementRefusedError, EnableOutcome
from synapse_ui_server.timezones import OfferedZones

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
    axon_reader_url="postgresql+psycopg://a@h/d",
    axon_project_id="test-project",
    axon_platform_oncall_email="oncall@test.invalid",
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
        offered: tuple[str, ...] = ("Asia/Kolkata",),
        source: str = "intersection",
        # What the PUBLISH returns, or raises. Defaults to a message id, so every test that is
        # not about delivery is unaffected by it.
        axon_outcome: str | Exception = "fake-message-id",
    ) -> tuple[httpx.AsyncClient, list[dict[str, Any]]]:
        app = create_app(_CONFIG)
        # NO LIFESPAN, so nothing tries to open a pool. The handlers only ever pass these to the
        # two functions stubbed below, which ignore them.
        app.state.engine = object()
        app.state.provision_engine = object()
        # AXON (slice 2). The enable route no longer sends: it PUBLISHES one message and
        # returns, and axon-sender does the provider call and the ledger write behind the queue.
        # So the state this fixture builds shrank from an engine plus an adapter plus an address
        # to a publisher plus an address.
        #
        # THE PUBLISHER IS A FAKE ON app.state, NOT A PATCH, and that is a real improvement over
        # the slice-1 shape. The route reaches it through the same attribute the lifespan sets,
        # so there is no name to patch and therefore no way for a test to pass against a route
        # that stopped calling it. The vacuity trap the old comment named is gone rather than
        # guarded against.
        app.state.axon_oncall_email = "oncall@test.invalid"

        sends: list[dict[str, Any]] = []

        class _FakePublisher:
            def publish(self, topic_name: str, data: bytes) -> str:
                sends.append({"topic": topic_name, "data": data})
                if isinstance(axon_outcome, Exception):
                    raise axon_outcome
                return axon_outcome

        app.state.axon_publisher = _FakePublisher()
        # THE OFFERED SET, which the lifespan would normally compute against the real database.
        # A REAL OfferedZones rather than a stub, so the route exercises the real `offers`; a
        # duck-typed fake could answer True to everything and every refusal test would pass
        # vacuously. Defaults to the one zone every other test in this file posts.
        app.state.timezones = OfferedZones(
            names=offered,
            source=source,  # type: ignore[arg-type]
            python_count=len(offered),
            postgres_count=len(offered) if source == "intersection" else None,
        )
        app.dependency_overrides[require_tenant_configure] = lambda: OPERATOR
        # AND require_platform, which the GET routes depend on DIRECTLY. Without it /timezones
        # reaches Auth0Verifier and dies on app.state.verifier, which no lifespan set here. The
        # enable route is unaffected either way: its gate is require_tenant_configure, overridden
        # above, and the real dependency chain is asserted separately below.
        app.dependency_overrides[require_platform] = lambda: OPERATOR

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

        # `sends` is attached rather than returned, so every existing call site keeps unpacking
        # a two-tuple and only the tests that care about delivery reach for it.
        app.state.axon_sends_for_test = sends
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
            analysis_id="dead_stock",
            tenant_name="TestCo",
            canonical_positions=15,
            warning=None,
            already_provisioned=False,
        ),
    )
    async with client:
        response = await client.post(_url(), json={"timezone": "Asia/Kolkata"})

    assert response.status_code == 201
    body = response.json()
    assert body["analysis_id"] == "dead_stock"
    assert body["warning"] is None
    # ECHOED EVEN WHEN FALSE, so the console chooses its copy from a field that is always there
    # rather than from the absence of one.
    assert body["already_provisioned"] is False
    # THE CONFIGURATION THE OPERATOR DID NOT CHOOSE IS ECHOED, so the console can say "silent
    # mode, daily" without restating constants it cannot see.
    assert body["cadence"] == "daily"
    assert body["rung"] == "shadow"
    assert len(calls) == 1


async def test_an_already_active_pair_is_a_409_and_does_not_write(gated_app) -> None:  # type: ignore[no-untyped-def]
    """IDEMPOTENT AT THE DATABASE, REPORTED AT THE EDGE.

    The write is idempotent at the database (pk_provision refuses the second row), so this could
    be left to the insert and answered as a duplicate. It is caught HERE instead, because the
    reader knows something the write path cannot: WHICH state the existing row is in. The 200 the
    duplicate path returns can only say "a row already existed", and the next case in this file is
    one where that difference is the entire message.
    """
    client, calls = gated_app(detail=_detail(analyses=(_active("dead_stock"),)))
    async with client:
        response = await client.post(_url(), json={"timezone": "Asia/Kolkata"})

    assert response.status_code == 409
    assert "already enabled" in response.json()["detail"]
    assert calls == [], "the write was attempted for a pair that is already active"


async def test_a_disabled_pair_is_a_409_and_never_reaches_the_write(gated_app) -> None:  # type: ignore[no-untyped-def]
    """THE ONE THIS FILE EXISTS FOR, AND THE ONE THAT SILENTLY SUCCEEDS IF IT IS MISSED.

    A disabled pair has a row, so the write would be refused on pk_provision and the endpoint
    would answer 200 "a row already existed", which is true and is nearly useless: it does not say
    the monitor was deliberately switched off, and it does not say re-enabling is unavailable by
    design. The refusal has to happen BEFORE the write, and it has to be distinguishable from
    "already enabled" because the operator needs different information in each case.

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
        "the write was attempted against a disabled pair. The database would have refused it on "
        "pk_provision and the endpoint would have answered 200 'a row already existed', losing "
        "the only explanation the operator can act on"
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


async def test_a_duplicate_at_the_write_is_200_and_says_so(gated_app) -> None:  # type: ignore[no-untyped-def]
    """THE RACE, AND THE STATUS CODE IS A DECISION ABOUT THE PAGE RATHER THAN ABOUT HTTP.

    Reaching this means the two reader checks above were STALE: they refuse both states they can
    see, so the realistic cause is a second operator enabling the same pair in between. The row
    exists and this request created nothing.

    NOT 201, which would claim a resource this request did not create. NOT 409 either, and that is
    the interesting half. 409 is the stronger semantic answer and it is what the same fact gets
    one step earlier, but cm-frontend's synapsePost THROWS on any non-2xx, so the server action
    returns {ok:false} and skips BOTH revalidatePath calls. The page would keep rendering Enable
    for a pair that now has a row, which is a console asserting a state the database contradicts:
    the exact defect this slice exists to remove. 200 revalidates and the page re-reads the truth.

    THE BODY HAS TO CARRY THE HONESTY THAT THE STATUS CODE GIVES UP. A 200 saying only "enabled"
    would be worse than the 409, so the flag and the warning are both asserted here.
    """
    client, calls = gated_app(
        detail=_detail(),
        outcome=EnableOutcome(
            analysis_id="dead_stock",
            tenant_name="TestCo",
            canonical_positions=15,
            warning=provision_module._ALREADY_PROVISIONED_WARNING,
            already_provisioned=True,
        ),
    )
    async with client:
        response = await client.post(_url(), json={"timezone": "Asia/Kolkata"})

    assert response.status_code == 200
    body = response.json()
    assert body["already_provisioned"] is True
    assert "WROTE NOTHING" in body["warning"]
    assert "TIMEZONE YOU CHOSE WAS NOT APPLIED" in body["warning"]
    assert len(calls) == 1, "the write was not attempted; this path is only reachable through it"


# ---------------------------------------------------------------------------
# AXON (slice 1): the enable route is the delivery plane's first producer
# ---------------------------------------------------------------------------


async def test_a_successful_enable_hands_the_event_to_axon(gated_app) -> None:  # type: ignore[no-untyped-def]
    """THE PRODUCER IS WIRED, asserted on what Axon was actually asked to send.

    THE SUBJECT IS AN OPAQUE PAIR, NOT A FOREIGN KEY, and that is checked here rather than left
    to the schema: (tenant, analysis) is what synapse.provision is keyed on and what a reader
    would go looking for, and it travels as text so Axon never needs to know Synapse exists.
    """
    client, _ = gated_app(
        detail=_detail(),
        outcome=EnableOutcome(
            analysis_id="dead_stock",
            tenant_name="TestCo",
            canonical_positions=15,
            warning=None,
            already_provisioned=False,
        ),
    )
    async with client:
        response = await client.post(_url(), json={"timezone": "Asia/Kolkata"})
        sends = client._transport.app.state.axon_sends_for_test

    assert response.status_code == 201
    assert len(sends) == 1, "the enable did not reach the delivery plane"
    # PARSED BACK THROUGH THE REAL ENVELOPE, not inspected as a dict. The bytes on the wire are
    # what axon-sender will read, so asserting on the parsed form is asserting the contract both
    # deployments share rather than this side's idea of it.
    sent = sends[0]
    assert sent["topic"] == TOPIC_SEND_REQUESTED
    envelope = SendRequested.from_json(sent["data"])
    assert envelope.notification_class == "synapse.provision.enabled"
    assert envelope.subject_kind == "synapse.provision"
    assert envelope.subject_id == f"{TENANT}:dead_stock"
    assert envelope.actor_subject == OPERATOR.subject
    assert envelope.recipient == "oncall@test.invalid"
    assert envelope.channel is Channel.EMAIL
    # THE ID THE WHOLE SLICE TURNS ON. Minted here, in the producer, because it is
    # pk_platform_deliveries: a redelivery carrying it reaches the same row and the second INSERT
    # is refused. A consumer-minted id would make every redelivery a new row.
    assert envelope.delivery_id.version == 7


async def test_a_publish_failure_does_not_fail_the_enable(gated_app) -> None:  # type: ignore[no-untyped-def]
    """THE COUPLING RULE, AND IT IS THE ONE THAT MATTERS MOST IN THIS PAIRING.

    The provision row is already committed when Axon is reached: enable_analysis's transaction
    closed when it returned. A message that did not reach the queue must not undo an enablement,
    and a response that turned 201 into a 500 would be reporting the delivery's failure as the
    enable's. The operator would then retry and get the 409 "already enabled" branch for a
    monitor that was in fact enabled the first time.

    THIS IS ALSO THE HOLE THE QUEUE DID NOT CLOSE. A publish that raises leaves the enablement
    committed with nothing queued, so no redelivery can rescue it: there is no message. Only a
    transactional outbox closes that, and main.py records what it would cost.
    """
    client, _ = gated_app(
        detail=_detail(),
        outcome=EnableOutcome(
            analysis_id="dead_stock",
            tenant_name="TestCo",
            canonical_positions=15,
            warning=None,
            already_provisioned=False,
        ),
        axon_outcome=RuntimeError("the delivery plane exploded"),
    )
    async with client:
        response = await client.post(_url(), json={"timezone": "Asia/Kolkata"})

    assert response.status_code == 201, (
        "an exception escaping the delivery plane failed the enable. The provision row is "
        "already committed at that point, so this turns a successful enablement into a 500."
    )
    body = response.json()
    assert body["analysis_id"] == "dead_stock"
    # AND THE RESPONSE SAYS NOTHING ABOUT THE DELIVERY. The operator enabled a monitor; whether
    # an internal notification reached on-call is not their business and not their failure.
    assert "delivery" not in body
    assert "axon" not in body


async def test_a_refused_enable_sends_nothing(gated_app) -> None:  # type: ignore[no-untyped-def]
    """NOTHING HAPPENED, SO NOTHING IS DELIVERED. A 409 on an already-enabled pair wrote no row
    and is not an event; mailing on-call about it would train them to ignore the channel."""
    client, _ = gated_app(detail=_detail(analyses=(_active("dead_stock"),)))
    async with client:
        response = await client.post(_url(), json={"timezone": "Asia/Kolkata"})
        sends = client._transport.app.state.axon_sends_for_test

    assert response.status_code == 409
    assert sends == []


async def test_the_duplicate_is_not_logged_as_an_enablement() -> None:
    """AN "ENABLED" EVENT ON A PATH THAT ENABLED NOTHING IS A FALSE AUDIT RECORD.

    The log line is the only artifact connecting a provisioning change to a person, and Cloud
    Logging is where an alert or a later question would read it. Filing a duplicate under
    synapse.provision.enabled would put a claim in that record which the database can disprove,
    which is the same class of defect as a comment describing a clause that no longer exists.

    ASSERTED ON THE SOURCE, matching the audit test below, because a caplog test passes while the
    event vocabulary drifts.
    """
    from pathlib import Path

    source = Path(main_module.__file__).read_text(encoding="utf-8")
    assert '"synapse.provision.already_provisioned"' in source, (
        "the duplicate path has no event value of its own, so it logs as an enablement"
    )
    assert '"already_provisioned": outcome.already_provisioned' in source


async def test_one_analysis_disabled_does_not_block_enabling_another(gated_app) -> None:  # type: ignore[no-untyped-def]
    """THE STATE IS PER PAIR, NOT PER TENANT. Without this the tests above would pass against a
    handler that refused any tenant with any disabled monitor."""
    client, calls = gated_app(
        detail=_detail(disabled=(_disabled("dead_stock"),)),
        outcome=EnableOutcome(
            analysis_id="stockout_risk",
            tenant_name="TestCo",
            canonical_positions=15,
            warning=None,
            already_provisioned=False,
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


async def test_a_timezone_refusal_is_422_carrying_the_message_verbatim(gated_app) -> None:  # type: ignore[no-untyped-def]
    """422: the request was understood and refused. THE MESSAGE IS THE PAYLOAD, because the zone
    cannot be changed after the fact and the sentence is the only thing the operator can act on.

    THE DOCSTRING HERE USED TO SAY the message "is the trigger's own sentence", which was the
    conflation the 5e timezone fix removed. TWO DIFFERENT REFUSALS reach this handler as the same
    exception type and they are NOT the same claim:

      the TRIGGER's, on the DBAPIError path in enable_analysis, where Postgres really did refuse
      the VALIDATOR's, from _validate, which is this service's own zoneinfo and reaches neither
        Postgres nor the trigger

    Both must pass through untouched, which is what this asserts by injecting an opaque marker
    rather than a plausible sentence: a handler that recognised and reworded either one would
    fail here. Which sentence each source produces is asserted where it is produced,
    test_provision.py, not restated in this file.

    THE ZONE IS IN THE OFFERED SET ON PURPOSE. The route's own membership check runs first and
    would otherwise answer with ITS message, and this test would then be asserting the wrong
    refusal while looking green. Offered-and-still-refused is also the real case it stands for:
    a degraded list, or a trigger that disagrees with what startup measured.
    """
    client, _ = gated_app(
        detail=_detail(),
        offered=("Mars/Olympus_Mons",),
        outcome=EnablementRefusedError(
            "REFUSAL-TEXT-FROM-BELOW, passed through unchanged", reason="bad_timezone"
        ),
    )
    async with client:
        response = await client.post(_url(), json={"timezone": "Mars/Olympus_Mons"})

    assert response.status_code == 422
    assert response.json()["detail"] == "REFUSAL-TEXT-FROM-BELOW, passed through unchanged"


async def test_a_zone_outside_the_offered_set_is_422_before_the_write(gated_app) -> None:  # type: ignore[no-untyped-def]
    """THE SECOND REFUSAL, AND IT IS THE ROUTE'S OWN.

    The offered set is the intersection of what this service resolves and what this Postgres
    accepts, read at startup and held on app.state. It is runtime environment state, so the write
    module cannot see it and the check lives here.

    THE DIRECTION THIS CLOSES is the one _validate cannot: a name this process resolves happily
    and the database refuses. Without it that reaches the INSERT and is refused by the trigger
    AFTER the operator has committed, which is a dead control that fails late.

    REFUSED, NOT TRANSLATED. The message says so, because the column is immutable and storing a
    value nobody typed is worse than refusing one.
    """
    client, calls = gated_app(detail=_detail(), offered=("Asia/Kolkata",))
    async with client:
        response = await client.post(_url(), json={"timezone": "Etc/UTC"})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "not one this console offers" in detail
    assert "INTERSECTION" in detail
    assert "refused rather than translated" in detail
    assert calls == [], "a zone outside the offered set reached the write"


async def test_a_zone_inside_the_offered_set_proceeds(gated_app) -> None:  # type: ignore[no-untyped-def]
    """THE BASELINE. Without it the test above passes against a route that refuses every zone,
    which is exactly the shape of the bug being fixed."""
    client, calls = gated_app(
        detail=_detail(),
        offered=("Asia/Kolkata",),
        outcome=EnableOutcome(
            analysis_id="dead_stock",
            tenant_name="TestCo",
            canonical_positions=15,
            warning=None,
            already_provisioned=False,
        ),
    )
    async with client:
        response = await client.post(_url(), json={"timezone": "Asia/Kolkata"})

    assert response.status_code == 201
    assert len(calls) == 1


async def test_the_degraded_list_says_so_in_the_refusal(gated_app) -> None:  # type: ignore[no-untyped-def]
    """WHEN THE LIST IS PYTHON-ONLY, THE REFUSAL SAYS THE LIST MIGHT BE WRONG.

    A degraded set can both refuse a name the database would accept and offer one it would not.
    An operator hitting the first case against a silently degraded list would conclude the zone
    does not exist. Saying it is degraded is the difference between a refusal and a lie.
    """
    client, _ = gated_app(detail=_detail(), offered=("Asia/Kolkata",), source="python_only")
    async with client:
        response = await client.post(_url(), json={"timezone": "Etc/UTC"})

    assert response.status_code == 422
    assert "DEGRADED" in response.json()["detail"]


async def test_the_timezones_endpoint_serves_the_offered_set_and_its_source(gated_app) -> None:  # type: ignore[no-untyped-def]
    """WHAT THE CONSOLE READS. `source` is part of the payload rather than a diagnostic: the page
    renders a note when it is python_only, because a fallback nobody can see is the dead-control
    class in the opposite direction."""
    client, _ = gated_app(detail=_detail(), offered=("Africa/Djibouti", "Asia/Kolkata"))
    async with client:
        response = await client.get("/timezones")

    assert response.status_code == 200
    body = response.json()
    assert body["timezones"] == ["Africa/Djibouti", "Asia/Kolkata"]
    assert body["source"] == "intersection"
    assert body["count"] == 2


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
            analysis_id="dead_stock",
            tenant_name="TestCo",
            canonical_positions=15,
            warning=None,
            already_provisioned=False,
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
            already_provisioned=False,
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
