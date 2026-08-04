"""The durable action log against a real Postgres. Two roles, two engines, one database.

NEEDS THE synapse SCHEMA, which is Synapse's own alembic chain rather than DIS's:

    SYNAPSE_ADMIN_URL=... uv run alembic -c synapse/alembic.ini upgrade head
    psql ... -f infra/db-setup/sql/04_synapse_writer_grant.sql

then, in addition to the reader DSN every other live test uses:

    SYNAPSE_WRITER_URL='postgresql+psycopg://synapse_writer:...@host:port/db'

TWO ENGINES IS THE POINT, not an inconvenience. The appender holds synapse_writer's engine
(INSERT, no SELECT, nothing on canonical); the reader holds synapse_reader's (SELECT on the log
and on two canonical tables, no INSERT anywhere). These tests are the only place that
distinction is OBSERVABLE — the unit suite can prove the types differ, but only a database can
prove the grants do.

EVERY TEST HERE TAKES ``require_appendable`` FIRST, and that is not ceremony. Four of these five
assert that something is REFUSED, and a refusal test is green when the entire write path is
broken. A staging run proved it: the trigger test failed while the other four passed, and the
log was fine — but the same four would have passed had it been empty, unreachable, or
ungranted. The fixture appends a probe and reads it back, so every refusal below is contrasted
against a write that demonstrably landed. See conftest.py's header for the class.

THESE TESTS WRITE UNDER A SYNTHETIC TENANT (``probe_tenant``), never the tenant with real data.
The table is append-only by trigger, so their rows are permanent and cannot be cleaned up; RLS
is the only isolation available, so it is the isolation used. Nothing here needs canonical data
— every event is fabricated — so the write side and the read-real-data side split cleanly.

WHAT THESE COVER THAT NOTHING ELSE CAN:
  - the idempotency split on real rows: a retry suppressed, a correction landing
  - the append-only trigger refusing UPDATE and DELETE, against rows it can actually see
  - RLS refusing a cross-tenant append, reading the GENERATED tenant_id
  - the writer genuinely having no SELECT, and the reader no INSERT
"""

from __future__ import annotations

import os
from collections.abc import Callable, Coroutine
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from synapse.core.action import Action, ActionEvent, Provenance, Verb
from synapse.core.holdout import Arm

READER_DSN = os.environ.get("SYNAPSE_READER_URL")
WRITER_DSN = os.environ.get("SYNAPSE_WRITER_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not READER_DSN or not WRITER_DSN,
        reason=(
            "needs SYNAPSE_WRITER_URL as well as SYNAPSE_READER_URL; the synapse schema comes "
            "from synapse/alembic.ini, not DIS's chain. SYNAPSE_TEST_TENANT_ID is deliberately "
            "NOT required — these tests append under a synthetic tenant and read no real data"
        ),
    ),
]

RequireAppendable = Callable[..., Coroutine[Any, Any, UUID]]


def _event(
    *,
    tenant: UUID,
    sku: str,
    quantity: Decimal | None = Decimal("40.000"),
    supersedes: UUID | None = None,
) -> ActionEvent:
    """One event. A fresh event_id every time, so identity never explains a suppression."""
    as_of = date(2026, 8, 5)
    return ActionEvent(
        event_id=uuid4(),
        recorded_at=datetime.now(UTC),
        supersedes=supersedes,
        action=Action(
            target={"tenant_id": str(tenant), "sku_id": sku},
            verb=Verb.REVIEW,
            quantity_at_stake=quantity,
            expires_on=as_of + timedelta(days=30),
            arm=Arm.TREATMENT,
            provenance=Provenance(
                declaration_id="dead_stock",
                declaration_version="0.1.0",
                capability_versions={"current_state": "0.1.0", "last_sale_at": "0.1.0"},
                thresholds={"stale_after_days": 90, "expires_after_days": 30},
                as_of=as_of,
            ),
        ),
    )


async def test_a_retry_is_suppressed_and_a_correction_lands(
    require_appendable: RequireAppendable,
    probe_tenant: UUID,
) -> None:
    """THE IDEMPOTENCY SPLIT, on real rows, through the two roles that will use it.

    Three appends of the same natural key: the original, a RETRY (identical payload, new
    event_id), and a CORRECTION (different quantity, so a different payload_hash). Two rows must
    result.

    This is migration 0019's lesson re-proved one layer up. Uniqueness on the natural key ALONE
    would have suppressed the correction too — which is exactly how canonical would have
    silently dropped source corrections — and the payload hash is what splits the two cases.

    The count is taken through synapse_reader, because synapse_writer holds no SELECT and cannot
    observe its own suppression. That is the posture working, not a limitation to route around.

    THE ONE TEST HERE THAT COULD NEVER PASS VACUOUSLY — it asserts two rows against a freshly
    randomised SKU, so an empty table fails it. It takes the fixture anyway, so that a broken
    write path is reported as a broken write path rather than as a failed dedup claim.
    """
    from dis_rls import create_rls_engine
    from synapse.persistence.action_log_postgres import (
        PostgresActionAppender,
        PostgresActionReader,
    )

    await require_appendable("it must distinguish a suppressed retry from a write that never landed")

    sku = f"SKU-IDEMPOTENCY-{uuid4().hex[:8]}"
    writer = create_rls_engine(WRITER_DSN)
    reader = create_rls_engine(READER_DSN)
    try:
        appender = PostgresActionAppender(writer, probe_tenant)
        original = _event(tenant=probe_tenant, sku=sku)
        await appender.append(original)
        await appender.append(_event(tenant=probe_tenant, sku=sku))  # RETRY: same payload
        await appender.append(
            _event(
                tenant=probe_tenant,
                sku=sku,
                quantity=Decimal("12.000"),
                supersedes=original.event_id,
            )
        )  # CORRECTION: different payload

        events = await PostgresActionReader(reader, probe_tenant).events()
    finally:
        await writer.dispose()
        await reader.dispose()

    mine = [e for e in events if e.action.target.get("sku_id") == sku]
    assert len(mine) == 2, (
        f"expected the original and the correction, got {len(mine)}. Three appends of one "
        "natural key: if this is 3 the retry was not suppressed; if 1 the correction was"
    )
    assert {e.action.quantity_at_stake for e in mine} == {Decimal("40.000"), Decimal("12.000")}
    assert any(e.supersedes == original.event_id for e in mine), "the correction names its cause"


async def test_the_trigger_refuses_an_update_and_a_delete(
    require_appendable: RequireAppendable,
    probe_tenant: UUID,
) -> None:
    """APPEND-ONLY AT THE DATABASE, tested through a role that could otherwise do it.

    The writer cannot UPDATE because it has no grant — which proves nothing about the trigger.
    This runs as the ADMIN role, which HAS every privilege, so the only thing that can refuse it
    is the trigger. That is the mechanism a REVOKE can never provide.

    IT SETS THE GUCs, AND THAT IS THE WHOLE HISTORY OF THIS TEST. It first ran without them and
    failed with DID NOT RAISE, which read as a missing trigger and was nothing of the kind:
    synapse.actions is FORCE ROW LEVEL SECURITY, so the policy applies to the table OWNER too,
    and Cloud SQL's `postgres` is NOSUPERUSER NOBYPASSRLS like anything else. With no
    app.tenant_id set, the UPDATE matched zero VISIBLE rows and a BEFORE UPDATE trigger cannot
    fire on a row it cannot see. The rows were there the whole time.

    So this asserts its precondition twice over: the probe landed, AND this session can SEE rows
    to update. Without the second, `UPDATE 0` and a refusal are indistinguishable to
    pytest.raises — which is exactly how the original passed review.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    await require_appendable("the trigger can only refuse an UPDATE that matches a visible row")

    admin_dsn = os.environ.get("SYNAPSE_ADMIN_URL")
    if not admin_dsn:
        pytest.fail(
            "SYNAPSE_ADMIN_URL is not set — the append-only trigger proof refuses to skip. "
            "A grant-based refusal would prove the grant, not the trigger"
        )

    scope = (
        "SELECT set_config('app.user_type', 'TENANT', true), "
        f"set_config('app.tenant_id', '{probe_tenant}', true)"
    )
    engine = create_async_engine(admin_dsn)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(scope))
            visible = int((await conn.execute(text("SELECT count(*) FROM synapse.actions"))).scalar_one())
            assert visible > 0, (
                "the admin session can see no rows in synapse.actions even with app.tenant_id "
                f"set to {probe_tenant}, yet the probe append just succeeded. An UPDATE here "
                "would match nothing and the trigger would never fire, so this test would pass "
                "having proved nothing. Check that SYNAPSE_ADMIN_URL points at the same "
                "database as SYNAPSE_WRITER_URL"
            )

            # THE NEGATIVE CONTROL, which is the bug this test shipped with, written down as an
            # assertion. A statement matching no row is refused by NOTHING — no error, rowcount
            # zero. If this raised, the trigger would be firing per-statement and the refusals
            # below would prove far less than they appear to.
            missed = await conn.execute(
                text("UPDATE synapse.actions SET verb = 'review' WHERE event_id = :nobody"),
                {"nobody": str(UUID(int=0))},
            )
            assert missed.rowcount == 0, "the sentinel id must match nothing"

        async with engine.begin() as conn:
            await conn.execute(text(scope))
            with pytest.raises(Exception, match="append-only"):
                await conn.execute(text("UPDATE synapse.actions SET verb = 'review'"))
        async with engine.begin() as conn:
            await conn.execute(text(scope))
            with pytest.raises(Exception, match="append-only"):
                await conn.execute(text("DELETE FROM synapse.actions"))
    finally:
        await engine.dispose()


async def test_rls_refuses_an_append_for_another_tenant(
    require_appendable: RequireAppendable,
    probe_tenant: UUID,
) -> None:
    """The policy reads the GENERATED tenant_id, derived from target — proved by consequence.

    A policy that referenced a NULL would let this through. The append below sets the session to
    one tenant and hands over an event whose TARGET names another; the database must refuse it,
    which it can only do by evaluating the generated column at insert time.

    THE LEGITIMATE APPEND ON THE SAME APPENDER IS THE POINT. On its own, "a cross-tenant append
    raises" is satisfied by an appender that raises at every call — a broken DSN, a revoked
    grant, a policy that refuses everything. Appending a valid event through the SAME object
    first turns this from "something was refused" into "this specific thing was refused and its
    legitimate twin was not", which is the only version that says anything about tenancy.
    """
    from dis_rls import create_rls_engine
    from synapse.persistence.action_log_postgres import PostgresActionAppender

    await require_appendable("a refusal means nothing unless a legitimate append succeeds")

    other_tenant = UUID("aaaaaaaa-0000-0000-0000-00000000000a")
    assert other_tenant != probe_tenant, "the two tenants must differ or nothing is being tested"

    writer = create_rls_engine(WRITER_DSN)
    try:
        appender = PostgresActionAppender(writer, probe_tenant)

        # THE BASELINE: the same appender, the same session scope, a target naming its own
        # tenant. If this raises, the test fails here rather than passing on the refusal below.
        await appender.append(_event(tenant=probe_tenant, sku=f"SKU-BASELINE-{uuid4().hex[:8]}"))

        with pytest.raises(Exception, match="row-level security"):
            await appender.append(_event(tenant=other_tenant, sku="SKU-CROSS-TENANT"))
    finally:
        await writer.dispose()


async def test_the_writer_cannot_read_and_the_reader_cannot_write(
    require_appendable: RequireAppendable,
    probe_tenant: UUID,
) -> None:
    """THE GRANTS, observed. The unit suite proves the TYPES differ; only this proves the roles do.

    Three layers say the writer cannot read — the grant, the engine, and the type. This is the
    one that checks the first.

    The fixture is what stops this being green against a database where NOTHING works: two
    "permission denied" assertions are equally satisfied by a writer with no grants at all, and
    the probe establishes that the writer can in fact write and the reader in fact read before
    either refusal is believed.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    await require_appendable("permission-denied assertions pass for a role that can do nothing")

    writer = create_async_engine(str(WRITER_DSN))
    reader = create_async_engine(str(READER_DSN))
    try:
        async with writer.connect() as conn:
            with pytest.raises(Exception, match="permission denied"):
                await conn.execute(text("SELECT count(*) FROM synapse.actions"))
        async with reader.connect() as conn:
            with pytest.raises(Exception, match="permission denied"):
                await conn.execute(
                    text(
                        "INSERT INTO synapse.actions (event_id, recorded_at, target, verb, "
                        "expires_on, arm, declaration_id, declaration_version, "
                        "capability_versions, thresholds, as_of, payload_hash) VALUES "
                        '(gen_random_uuid(), now(), \'{"tenant_id":"'
                        + str(probe_tenant)
                        + "\"}', 'review', current_date, 'treatment', 'x', '0.1.0', "
                        "'{\"a\":\"0.1.0\"}', '{}', current_date, 'h')"
                    )
                )
    finally:
        await writer.dispose()
        await reader.dispose()


async def test_the_writer_holds_nothing_on_canonical(
    require_appendable: RequireAppendable,
) -> None:
    """The converse of the split, and the half that is easy to forget: the action log must not be
    able to read tenant data even by accident.

    Same vacuity risk as the test above and the same guard: "permission denied on canonical" is
    what a completely unusable credential also reports.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    await require_appendable("a dead credential is also denied on canonical")

    writer = create_async_engine(str(WRITER_DSN))
    try:
        async with writer.connect() as conn:
            with pytest.raises(Exception, match="permission denied"):
                await conn.execute(text("SELECT count(*) FROM canonical.store_sku_current_position"))
    finally:
        await writer.dispose()
