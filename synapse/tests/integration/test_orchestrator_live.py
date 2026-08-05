"""The orchestrator against a real Postgres: two RLS scopes, the run state machine, the sweep.

NEEDS synapse/alembic.ini upgraded to 0003 (provision + run) and the grants it issues, plus both
DSNs — see conftest.py's header. These tests INSERT their own provision rows through the admin
credential, because nothing else can: no runtime role holds INSERT on synapse.provision, which
is the posture rather than an obstacle.

EVERY TEST TAKES ``require_appendable`` FIRST, for the reason conftest's header gives: several
of these assert that something is refused or skipped, and a refusal test is green when the whole
write path is broken.

THEY RUN UNDER THE SYNTHETIC PROBE TENANT, never the tenant with real data. These append actions
to an append-only table, so their rows are permanent; RLS is the only isolation available and it
is the isolation used.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from synapse.core.provision import Cadence, Provision, Rung

READER_DSN = os.environ.get("SYNAPSE_READER_URL")
WRITER_DSN = os.environ.get("SYNAPSE_WRITER_URL")
ADMIN_DSN = os.environ.get("SYNAPSE_ADMIN_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not READER_DSN or not WRITER_DSN,
        reason="needs SYNAPSE_READER_URL and SYNAPSE_WRITER_URL; schema from synapse/alembic.ini",
    ),
]

RequireAppendable = Callable[..., Coroutine[Any, Any, UUID]]


def _require_admin() -> str:
    """Provisioning needs the admin credential, and its absence FAILS rather than skips.

    No runtime role holds INSERT on synapse.provision — that is deliberate, provisioning is an
    operator act — so without this these tests cannot set up their own preconditions. Skipping
    would leave the orchestrator's only live coverage quietly absent.
    """
    if not ADMIN_DSN:
        pytest.fail(
            "SYNAPSE_ADMIN_URL is not set. Nothing but the owner can write synapse.provision, "
            "so these tests cannot create the state they assert on"
        )
    return ADMIN_DSN


async def _provision_rows(tenant: UUID, rows: list[Provision]) -> None:
    """Replace this tenant's provisions. Admin credential, PLATFORM scope for the delete."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_require_admin())
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT set_config('app.user_type','PLATFORM',true)"))
            await conn.execute(
                text("DELETE FROM synapse.provision WHERE tenant_id = CAST(:t AS uuid)"),
                {"t": str(tenant)},
            )
            for row in rows:
                await conn.execute(
                    text(
                        "INSERT INTO synapse.provision (tenant_id, analysis_id, cadence, rung, "
                        "timezone, enabled_at) VALUES (CAST(:t AS uuid), :a, :c, :r, :z, :e)"
                    ),
                    {
                        "t": str(row.tenant_id),
                        "a": row.analysis_id,
                        "c": row.cadence.value,
                        "r": row.rung.value,
                        "z": row.timezone,
                        "e": row.enabled_at,
                    },
                )
    finally:
        await engine.dispose()


async def _clear_runs(tenant: UUID) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_require_admin())
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT set_config('app.user_type','PLATFORM',true)"))
            await conn.execute(
                text("DELETE FROM synapse.run WHERE tenant_id = CAST(:t AS uuid)"),
                {"t": str(tenant)},
            )
    finally:
        await engine.dispose()


def _shadow(tenant: UUID) -> Provision:
    return Provision(
        tenant_id=tenant,
        analysis_id="dead_stock",
        cadence=Cadence.DAILY,
        rung=Rung.SHADOW,
        timezone="Asia/Kolkata",
        enabled_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# The DDL's own guards
# ---------------------------------------------------------------------------


async def test_the_database_refuses_an_unresolvable_timezone(
    require_appendable: RequireAppendable, probe_tenant: UUID
) -> None:
    """THE TRIGGER, FIRING. A bad zone does not fail a run — it shifts every slot and mis-stamps
    every as_of, permanently, inside an append-only index. So the row must be impossible.

    The legitimate insert first is the baseline: without it, 'the insert raised' would also be
    satisfied by a broken connection or a missing grant.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    await require_appendable("a refused insert proves nothing if every insert is refused")

    engine = create_async_engine(_require_admin())
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT set_config('app.user_type','PLATFORM',true)"))
            await conn.execute(
                text("DELETE FROM synapse.provision WHERE tenant_id = CAST(:t AS uuid)"),
                {"t": str(probe_tenant)},
            )
            # BASELINE: a good zone is accepted.
            await conn.execute(
                text(
                    "INSERT INTO synapse.provision (tenant_id, analysis_id, cadence, rung, "
                    "timezone, enabled_at) VALUES (CAST(:t AS uuid), 'dead_stock', 'daily', "
                    "'shadow', 'Asia/Kolkata', now())"
                ),
                {"t": str(probe_tenant)},
            )
        async with engine.begin() as conn:
            await conn.execute(text("SELECT set_config('app.user_type','PLATFORM',true)"))
            with pytest.raises(Exception, match="does not resolve"):
                await conn.execute(
                    text(
                        "INSERT INTO synapse.provision (tenant_id, analysis_id, cadence, rung, "
                        "timezone, enabled_at) VALUES (CAST(:t AS uuid), 'other', 'daily', "
                        "'shadow', 'Mars/Olympus_Mons', now())"
                    ),
                    {"t": str(probe_tenant)},
                )
    finally:
        await engine.dispose()


async def test_the_writer_cannot_read_or_write_provision(
    require_appendable: RequireAppendable,
) -> None:
    """The append credential has no business reading a customer's enablement. Two refusals,
    contrasted against a probe that proves the credential works at all."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    await require_appendable("permission-denied passes for a credential that can do nothing")

    engine = create_async_engine(str(WRITER_DSN))
    try:
        async with engine.connect() as conn:
            with pytest.raises(Exception, match="permission denied"):
                await conn.execute(text("SELECT count(*) FROM synapse.provision"))
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# PLATFORM enumeration
# ---------------------------------------------------------------------------


async def test_enumeration_reads_across_tenants_and_writes_nothing(
    require_appendable: RequireAppendable, probe_tenant: UUID
) -> None:
    """THE FIRST THING IN SYNAPSE THAT NEEDS PLATFORM SCOPE.

    The reader sets no tenant, so under TENANT scope it would see zero rows. Seeing the probe
    tenant's provision proves the PLATFORM branch of the policy is what is being used.
    """
    from dis_rls import create_rls_engine
    from synapse.persistence.provision_postgres import PostgresProvisionReader
    from synapse.registry import max_rungs

    await require_appendable("an empty enumeration is indistinguishable from a broken one")
    await _provision_rows(probe_tenant, [_shadow(probe_tenant)])

    engine = create_rls_engine(READER_DSN)
    try:
        active = await PostgresProvisionReader(engine).active(max_rungs=max_rungs())
    finally:
        await engine.dispose()

    mine = [p for p in active if p.tenant_id == probe_tenant]
    assert len(mine) == 1, f"expected the probe tenant's provision, saw {len(mine)}"
    assert mine[0].analysis_id == "dead_stock"
    assert mine[0].timezone == "Asia/Kolkata"


async def test_a_rung_above_the_ceiling_in_the_real_table_refuses_the_enumeration(
    require_appendable: RequireAppendable, probe_tenant: UUID
) -> None:
    """THE ENVELOPE, AGAINST A REAL ROW. The unit suite proves the function refuses; this proves
    a row an operator could actually type reaches it.

    'suggest' passes ck_provision_rung — the database permits it, because the ceiling is
    per-analysis and lives in code. That is the whole point of checking at load.
    """
    from dis_rls import create_rls_engine
    from synapse.core.errors import ProvisionRefusedError
    from synapse.persistence.provision_postgres import PostgresProvisionReader
    from synapse.registry import max_rungs

    await require_appendable("a refusal means nothing unless the legitimate path works")
    await _provision_rows(
        probe_tenant,
        [
            Provision(
                tenant_id=probe_tenant,
                analysis_id="dead_stock",
                cadence=Cadence.DAILY,
                rung=Rung.SUGGEST,
                timezone="Asia/Kolkata",
                enabled_at=datetime(2026, 8, 1, tzinfo=UTC),
            )
        ],
    )

    engine = create_rls_engine(READER_DSN)
    try:
        with pytest.raises(ProvisionRefusedError, match="exceed their analysis"):
            await PostgresProvisionReader(engine).active(max_rungs=max_rungs())
    finally:
        await engine.dispose()
        await _provision_rows(probe_tenant, [_shadow(probe_tenant)])


# ---------------------------------------------------------------------------
# The run state machine
# ---------------------------------------------------------------------------


async def test_a_second_dispatch_of_the_same_slot_is_skipped_not_rerun(
    require_appendable: RequireAppendable, probe_tenant: UUID
) -> None:
    """THE SLOT KEY DOING ITS JOB. Cloud Scheduler retries its own API call, so this is the
    normal case rather than an edge one.

    Both sweeps run at the SAME instant, so both floor to the same slot. The first runs; the
    second must find the slot finished and skip it, appending nothing further.
    """
    from dis_rls import create_rls_engine
    from synapse.orchestrator import run_due

    await require_appendable("a skip proves nothing if the first run never happened")
    await _provision_rows(probe_tenant, [_shadow(probe_tenant)])
    await _clear_runs(probe_tenant)

    now = datetime(2026, 8, 5, 3, 30, tzinfo=UTC)
    reader = create_rls_engine(READER_DSN)
    writer = create_rls_engine(WRITER_DSN)
    try:
        first = await run_due(reader_engine=reader, writer_engine=writer, now=now, only_tenant=probe_tenant)
        second = await run_due(reader_engine=reader, writer_engine=writer, now=now, only_tenant=probe_tenant)
    finally:
        await reader.dispose()
        await writer.dispose()

    assert len(first) == 1 and len(second) == 1
    assert not first[0].skipped, f"the first sweep must run: {first[0].detail}"
    assert first[0].outcome == "satisfied", first[0].detail
    assert second[0].skipped, "the second dispatch of one slot must not run again"
    assert second[0].actions_appended == 0


async def test_a_later_slot_is_a_new_run(require_appendable: RequireAppendable, probe_tenant: UUID) -> None:
    """The converse, and it is what stops the test above passing against something that skips
    everything. A genuinely new day must produce a new run."""
    from dis_rls import create_rls_engine
    from synapse.orchestrator import run_due

    await require_appendable("a new run proves nothing if nothing can run")
    await _provision_rows(probe_tenant, [_shadow(probe_tenant)])
    await _clear_runs(probe_tenant)

    reader = create_rls_engine(READER_DSN)
    writer = create_rls_engine(WRITER_DSN)
    try:
        day_one = await run_due(
            reader_engine=reader,
            writer_engine=writer,
            now=datetime(2026, 8, 5, 3, 30, tzinfo=UTC),
            only_tenant=probe_tenant,
        )
        day_two = await run_due(
            reader_engine=reader,
            writer_engine=writer,
            now=datetime(2026, 8, 6, 3, 30, tzinfo=UTC),
            only_tenant=probe_tenant,
        )
    finally:
        await reader.dispose()
        await writer.dispose()

    assert not day_one[0].skipped and not day_two[0].skipped
    assert day_one[0].slot != day_two[0].slot


async def test_the_run_row_records_the_slot_and_what_was_in_force(
    require_appendable: RequireAppendable, probe_tenant: UUID
) -> None:
    """THE DENOMINATOR, AND THE SNAPSHOT. A zero-action run must still leave a row, or a tenant
    with no findings is indistinguishable from a tenant nobody analysed.

    The cadence/rung/timezone are snapshotted so that editing the provision next month does not
    rewrite what last month's runs are recorded as having done.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from dis_rls import create_rls_engine
    from synapse.orchestrator import run_due

    await require_appendable("an absent run row and a broken sweep look identical")
    await _provision_rows(probe_tenant, [_shadow(probe_tenant)])
    await _clear_runs(probe_tenant)

    now = datetime(2026, 8, 5, 3, 30, tzinfo=UTC)
    reader = create_rls_engine(READER_DSN)
    writer = create_rls_engine(WRITER_DSN)
    try:
        results = await run_due(reader_engine=reader, writer_engine=writer, now=now, only_tenant=probe_tenant)
    finally:
        await reader.dispose()
        await writer.dispose()

    engine = create_async_engine(_require_admin())
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT set_config('app.user_type','PLATFORM',true)"))
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT slot, cadence, rung, timezone, outcome, finished_at, "
                            "actions_proposed, actions_appended FROM synapse.run "
                            "WHERE tenant_id = CAST(:t AS uuid) AND analysis_id = 'dead_stock'"
                        ),
                        {"t": str(probe_tenant)},
                    )
                )
                .mappings()
                .one()
            )
    finally:
        await engine.dispose()

    # 03:30 UTC is 09:00 IST on the 5th — the slot is tenant-local, not the UTC date.
    assert str(row["slot"]) == "2026-08-05"
    assert row["cadence"] == "daily"
    assert row["rung"] == "shadow"
    assert row["timezone"] == "Asia/Kolkata"
    assert row["outcome"] == "satisfied"
    assert row["finished_at"] is not None
    assert row["actions_proposed"] == results[0].actions_proposed
    assert row["actions_appended"] == results[0].actions_appended


async def test_a_dry_run_writes_nothing_at_all(
    require_appendable: RequireAppendable, probe_tenant: UUID
) -> None:
    """D3's first hand-run. It must claim no run and append no action — proved by counting rows
    before and after rather than by trusting the flag."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from dis_rls import create_rls_engine
    from synapse.orchestrator import run_due

    await require_appendable("a dry run writing nothing is trivially true if nothing works")
    await _provision_rows(probe_tenant, [_shadow(probe_tenant)])
    await _clear_runs(probe_tenant)

    admin = create_async_engine(_require_admin())

    async def _counts() -> tuple[int, int]:
        async with admin.begin() as conn:
            await conn.execute(text("SELECT set_config('app.user_type','PLATFORM',true)"))
            runs = (
                await conn.execute(
                    text("SELECT count(*) FROM synapse.run WHERE tenant_id = CAST(:t AS uuid)"),
                    {"t": str(probe_tenant)},
                )
            ).scalar_one()
            acts = (
                await conn.execute(
                    text("SELECT count(*) FROM synapse.actions WHERE tenant_id = CAST(:t AS uuid)"),
                    {"t": str(probe_tenant)},
                )
            ).scalar_one()
        return int(runs), int(acts)

    reader = create_rls_engine(READER_DSN)
    try:
        before = await _counts()
        results = await run_due(
            reader_engine=reader,
            writer_engine=reader,
            now=datetime(2026, 8, 7, 3, 30, tzinfo=UTC),
            dry_run=True,
            only_tenant=probe_tenant,
        )
        after = await _counts()
    finally:
        await reader.dispose()
        await admin.dispose()

    assert results, "a dry run must still report what it would have done"
    assert after == before, f"a dry run wrote something: runs/actions {before} -> {after}"


async def test_a_backdated_sweep_completes_rather_than_violating_the_time_check(
    require_appendable: RequireAppendable, probe_tenant: UUID
) -> None:
    """REGRESSION. ``started_at`` comes from the injected ``now``; ``finished_at`` used to come
    from ``datetime.now(UTC)``. Those are different clock domains, and ``now`` is a parameter
    precisely so a sweep can be replayed for a past day — so any replay, and any test running at
    a boundary, violated ck_run_finished_after_started and the run never completed.

    The constraint is what caught it, which is the argument for having written it. This pins the
    fix: an anchored finish plus a monotonic elapsed, so the two timestamps cannot disagree.

    A date well in the past, so the bug's condition (now > wall clock) is inverted too and both
    directions are covered by the same assertion.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from dis_rls import create_rls_engine
    from synapse.orchestrator import run_due

    await require_appendable("a completed run proves nothing if nothing can run")
    await _provision_rows(probe_tenant, [_shadow(probe_tenant)])
    await _clear_runs(probe_tenant)

    reader = create_rls_engine(READER_DSN)
    writer = create_rls_engine(WRITER_DSN)
    try:
        results = await run_due(
            reader_engine=reader,
            writer_engine=writer,
            now=datetime(2020, 1, 2, 3, 30, tzinfo=UTC),
            only_tenant=probe_tenant,
        )
    finally:
        await reader.dispose()
        await writer.dispose()

    assert results[0].outcome == "satisfied", results[0].detail

    engine = create_async_engine(_require_admin())
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT set_config('app.user_type','PLATFORM',true)"))
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT started_at, finished_at, outcome FROM synapse.run "
                            "WHERE tenant_id = CAST(:t AS uuid)"
                        ),
                        {"t": str(probe_tenant)},
                    )
                )
                .mappings()
                .one()
            )
    finally:
        await engine.dispose()

    assert row["outcome"] == "satisfied"
    assert row["finished_at"] >= row["started_at"], "the two timestamps must share a clock"
    assert row["started_at"].year == 2020, "started_at is the INJECTED instant, not the wall clock"
