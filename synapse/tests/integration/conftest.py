"""Shared vacuity guard for Synapse's live tests, and how to run them at all.

HOW TO RUN THESE AGAINST STAGING — the whole invocation, in one copy-pasteable place, because
it has four requirements and three of them fail in ways that do not name themselves.

    cd dis && \\
      DIS_EXPECTED_DATABASE=thalamus \\
      SYNAPSE_READER_URL='postgresql+psycopg://synapse_reader:<PW>@10.55.0.3:5432/thalamus?sslmode=require' \\
      SYNAPSE_TEST_TENANT_ID='<tenant-uuid>' \\
      uv run pytest -c pyproject.toml -p no:dis_testing ../synapse/tests/integration

Each part, and what its absence looks like:

- ``SYNAPSE_READER_URL`` — the synapse_reader DSN. NOT ithina_dis_user, which holds full DML on
  canonical and would make a read-only plane's tests prove nothing about its read-only-ness.
  The password is in Secret Manager as ``thalamus-synapse_reader-password``; the assembled DSN
  is ``synapse-reader-database-url``, created by hand (Terraform only reads those). Driver is
  ``postgresql+psycopg``, never asyncpg — asyncpg is not a workspace dependency and the wrong
  scheme fails as ``ModuleNotFoundError``, which reads as a missing package rather than a bad
  DSN.
- ``DIS_EXPECTED_DATABASE=thalamus`` — dis-rls refuses any database except its expected one,
  defaulting to the local ``ithina_dis_db``. Without this every test fails with
  ``RlsContextError`` before touching a row. Not a permission error, and not obviously a
  config one.
- ``-p no:dis_testing`` — ``dis-testing`` registers a ``pytest11`` entry point, so it
  auto-loads into any suite that has the package installed, which Synapse does via the shared
  uv workspace. Its session-scoped autouse ``_dis_identity_synced`` runs an identity-mirror
  sync that assumes the LOCAL stack. Against staging it must be off.
- NETWORK ACCESS. The instance is ``ipv4_enabled = false`` — private IP only,
  ``ssl_mode = ENCRYPTED_ONLY`` — so the DSN above (10.55.0.3) is only reachable from inside
  the VPC: the Cloud SQL Auth Proxy, or a VM / Cloud Shell in it. **Whatever access is opened
  to run this must be closed afterwards.** Opening a public-IP window out of band also drifts
  the instance from Terraform, where ``ipv4_enabled`` is false.

Locally, only the first is needed —
``postgresql+psycopg://synapse_reader:synapse_reader_password@localhost:5433/ithina_dis_db``
plus the tenant id. ``DIS_EXPECTED_DATABASE`` already defaults to the local database name, and
``dis_testing``'s sync is correct there.

WHY THIS FILE EXISTS. Several tests in this directory prove statements about ROWS. Run against a
canonical schema with no rows, every one of them reduces to ``0 == 0`` and reports success
having verified nothing. A skipped test is quiet and honest; a GREEN test that proved nothing
gets believed, cited in reviews, and is strictly worse than a red one.

So those tests take the ``require_canonical_rows`` fixture and RAISE — never skip — when the
table is empty. The posture is dis/tests/integration/test_rls_platform_session_guard.py,
which refuses to skip when its stack is absent.

THE DATA SITUATION, stated once here rather than in each test. ``make seed`` writes a single
``config.source_mappings`` row and explicitly nothing else: ``identity_mirror`` belongs to
mirror-sync, and NO fixture anywhere inserts sale events or current positions. Canonical rows
in a local devbox are RESIDUE from having run the streaming consumer's integration tests
against the same volume — arbitrary content, no guarantee of presence, nobody maintaining it.
Reading a green local run as proof of correction-collapse is reading residue.

A REFUSAL TEST PASSES WHEN EVERYTHING IS BROKEN. That is the SECOND vacuity class, and the
reason ``require_appendable`` exists alongside ``require_canonical_rows``. A test asserting only
that something is DENIED — a cross-tenant append refused, a write by a read-only role refused —
cannot distinguish "correctly denied" from "nothing works at all". Three of the five action-log
tests were exactly that shape, and all three passed during a staging run in which the
append-only trigger test failed; they would have passed just as green against an empty table, a
revoked grant, or an appender that raised on every call. The fix is STRUCTURAL rather than a
matter of care: prove the SUCCESS path in the same session, so a refusal is contrasted against a
working baseline instead of against a vacuum.

A FIXTURE RATHER THAN AN IMPORTABLE HELPER, deliberately: the suite runs under
``--import-mode=importlib`` with no ``__init__.py``, so a sibling-module import is fragile in
a way a fixture is not. Shared rather than copied per file because two byte-identical guards
in one directory is how the duplicated Pub/Sub poll loop started, and that is already a
ledger item.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import TextClause, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

# Keyed by the SHORT name a test asks for, so a test never spells a canonical table itself —
# these two are the only ones Synapse reads at all, and the only two its read-only role is
# granted when that role is provisioned.
_COUNTS: dict[str, TextClause] = {
    "sale_events": text(
        "SELECT COUNT(*) FROM canonical.store_sku_sale_events WHERE tenant_id = CAST(:tenant AS uuid)"
    ),
    "current_position": text(
        "SELECT COUNT(*) FROM canonical.store_sku_current_position WHERE tenant_id = CAST(:tenant AS uuid)"
    ),
}

Table = Literal["sale_events", "current_position"]
RequireRows = Callable[..., Coroutine[Any, Any, int]]


class CanonicalDataRequiredError(RuntimeError):
    """This test proves a statement about rows, and there are none.

    Raised, never skipped. See the module docstring for why that distinction is the whole
    point of this file.
    """


@pytest.fixture
def require_canonical_rows() -> RequireRows:
    """Count rows in scope; raise ``CanonicalDataRequiredError`` if there are none.

    Deliberately NOT a fixture that CREATES data. Synapse is read-only on canonical and must
    stay that way — the table-name containment test and the no-write-statement test both
    exist to keep it so, and a test helper that inserted rows would be the first crack. The
    only honest response to an empty table is to refuse.

    ``what`` names the claim the test cannot make without rows, so the failure says what is
    unproven rather than merely that something is missing.
    """

    async def _require(
        conn: AsyncConnection,
        tenant_id: object,
        *,
        table: Table,
        what: str,
    ) -> int:
        rows = int((await conn.execute(_COUNTS[table], {"tenant": str(tenant_id)})).scalar_one())
        if not rows:
            raise CanonicalDataRequiredError(
                f"no canonical rows in {table} for tenant {tenant_id} - this test cannot "
                f"prove anything without data ({what}). `make seed` does NOT write canonical; "
                "local rows are residue from streaming-consumer integration runs, not a "
                "fixture. Point SYNAPSE_READER_URL at staging, or run the consumer's "
                "integration suite first."
            )
        return rows

    return _require


# ---------------------------------------------------------------------------
# The action log: the write side, and the vacuity guard for refusal tests
# ---------------------------------------------------------------------------

# THE TENANT THE WRITE-SIDE TESTS APPEND UNDER, and deliberately NOT the tenant with real data.
#
# synapse.actions is append-only, enforced by a trigger that binds even the table owner, so
# every row a test writes is PERMANENT — there is no cleanup, by construction. What isolation
# remains is the isolation the table already has: RLS. Writing probes under a synthetic tenant
# puts them behind the same FORCE-RLS boundary that separates real tenants from each other, so
# no real tenant's session can ever see them. That reuses a mechanism already proven here rather
# than inventing a marker column every future reader must remember to filter on.
#
# Nothing constrains this value: the action log has no foreign key into any DIS schema (an
# append-only log must outlive what it references), so a synthetic tenant id is insertable and
# owns no canonical rows. Override with SYNAPSE_PROBE_TENANT_ID if that decision changes.
PROBE_TENANT_ID = UUID(os.environ.get("SYNAPSE_PROBE_TENANT_ID", "decafbad-0000-4000-8000-000000000001"))

# One probe per SESSION, not per test. The probe row is permanent, so five tests taking this
# fixture must not mean five rows: the first call appends and verifies, the rest reuse the
# verdict. Keyed by nothing — the session is the scope.
_PROBE_VERDICT: list[UUID] = []

RequireAppendable = Callable[..., Coroutine[Any, Any, UUID]]

# THE LAST PARAGRAPH IS THE ONE THAT COST A WHOLE INVESTIGATION, so it is in the failure message
# rather than in a runbook: a bare count against this table reads zero whatever the truth.
_DIAGNOSIS = (
    "Check, in order: that synapse/alembic.ini has been upgraded against THIS database, that "
    "sql/04 has granted synapse_writer INSERT and synapse_reader SELECT on synapse.actions, and "
    "that neither role reports rolbypassrls. When you go and look, SET THE GUCs: synapse.actions "
    "is FORCE ROW LEVEL SECURITY, so a psql session with no app.tenant_id matches zero rows even "
    "as the table owner, and even on Cloud SQL as `postgres`. A bare `SELECT count(*)` there "
    "reports 0 for a healthy log and for an empty one alike."
)


# ---------------------------------------------------------------------------
# Writing to a FORCE RLS table from a TEST, which is its own surface
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _platform_write(dsn: str, tenant_id: UUID) -> AsyncIterator[AsyncConnection]:
    """An admin transaction that can BOTH read across tenants AND write one tenant's rows.

    **PLATFORM ALONE IS NOT ENOUGH TO WRITE, AND THAT IS THE WHOLE POINT OF THIS HELPER.**
    Every policy in this project reads

        USING       (tenant_id = <app.tenant_id> OR app.user_type = 'PLATFORM')
        WITH CHECK  (tenant_id = <app.tenant_id>)

    so ``app.user_type='PLATFORM'`` widens READS ONLY. An INSERT under PLATFORM with no
    ``app.tenant_id`` fails with ``new row violates row-level security policy``. Both GUCs are
    required, and the tenant one is what satisfies WITH CHECK.

    THE NEXT PERSON WILL REACH FOR PLATFORM FIRST, because that is what the read path uses and
    because both of us did. It has now cost six separate incidents: a trigger test whose UPDATE
    matched no visible row, migration 0002's DELETE, the provisioning pre-flight, a verification
    snippet in sql/04, provision_analysis.sql's own INSERT, and eight orchestrator live tests
    that inserted provision rows.

    THOSE EIGHT ARE THE INSTRUCTIVE ONE. They passed for two slices — locally, where
    ``ithina_dis_admin`` is a SUPERUSER and bypasses RLS entirely — and failed the first time
    they met staging, whose ``postgres`` is ``rolsuper=f rolbypassrls=f`` like every other role.
    A live test that has only ever run locally proves nothing about staging if it needs any
    privilege at all.

    infra/db-setup/README.md carries the same convention for hand-run SQL files. THIS IS A
    DIFFERENT SURFACE writing to the same tables: test setup is code, not a .sql file, so that
    convention could never have covered it. One helper rather than a rule per call site, because
    a rule per call site is what produced eight of them.

    Transaction-local (``true``), so nothing leaks into whatever the caller does next.
    """
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT set_config('app.user_type', 'PLATFORM', true)"))
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"),
                {"tenant": str(tenant_id)},
            )
            yield conn
    finally:
        await engine.dispose()


PlatformWrite = Callable[[str, UUID], AbstractAsyncContextManager[AsyncConnection]]


@pytest.fixture
def platform_write() -> PlatformWrite:
    """``_platform_write``, handed over as a fixture rather than imported.

    A SIBLING IMPORT DOES NOT WORK HERE and this is not a style preference: the suite runs under
    ``--import-mode=importlib`` with no ``__init__.py``, so ``from conftest import ...`` raises
    ModuleNotFoundError. Tried it; seven tests failed on the import alone. The module docstring
    said so and is now demonstrated.
    """
    return _platform_write


@pytest.fixture
def probe_tenant() -> UUID:
    """The synthetic tenant the write-side tests append under.

    A FIXTURE RATHER THAN AN IMPORT for the reason in the module docstring: this suite runs under
    ``--import-mode=importlib`` with no ``__init__.py``, so a test module importing ``conftest``
    directly is fragile in a way that taking a fixture is not.
    """
    return PROBE_TENANT_ID


class ActionLogNotWritableError(RuntimeError):
    """An append did not land, and the tests that follow would prove nothing.

    Raised, never skipped — the same posture as :class:`CanonicalDataRequiredError` and for a
    sharper reason. Every refusal test in the action-log suite is green when the whole write
    path is broken; this is the one check that can tell the difference.
    """


@pytest.fixture
def require_appendable() -> RequireAppendable:
    """Append a probe event and read it back. Raise if it is not there.

    THE ONE THING THE REFUSAL TESTS CANNOT ESTABLISH FOR THEMSELVES. It exercises the entire
    write path end to end and through both roles: synapse_writer's INSERT, the RLS ``WITH CHECK``
    against the GENERATED tenant_id, the generated columns, and synapse_reader's SELECT. If any
    link is broken this raises, and every test that took the fixture fails loudly instead of
    passing on a refusal it never earned.

    The probe is UNIQUE per session rather than a fixed row, because a constant natural key would
    be suppressed by ``ON CONFLICT DO NOTHING`` on every run after the first — proving only that
    an old row is still readable, not that a write lands TODAY. One permanent row per run is the
    price of that distinction, and it is why the probe is session-scoped and synthetic-tenanted.
    """

    async def _require(what: str) -> UUID:
        if _PROBE_VERDICT:
            return _PROBE_VERDICT[0]

        from dis_rls import create_rls_engine
        from synapse.core.action import Action, ActionEvent, Provenance, Verb
        from synapse.core.holdout import Arm
        from synapse.persistence.action_log_postgres import (
            PostgresActionAppender,
            PostgresActionReader,
        )

        writer_dsn = os.environ.get("SYNAPSE_WRITER_URL")
        reader_dsn = os.environ.get("SYNAPSE_READER_URL")
        if not writer_dsn or not reader_dsn:  # pragma: no cover - the skipif catches this first
            raise ActionLogNotWritableError(
                "SYNAPSE_WRITER_URL and SYNAPSE_READER_URL are both required to prove the "
                "write path; the module-level skipif should have caught this"
            )

        as_of = date.today()
        probe = ActionEvent(
            event_id=uuid4(),
            recorded_at=datetime.now(UTC),
            action=Action(
                target={
                    "tenant_id": str(PROBE_TENANT_ID),
                    "sku_id": f"PROBE-{uuid4().hex[:12]}",
                },
                verb=Verb.REVIEW,
                quantity_at_stake=Decimal("1.000"),
                expires_on=as_of + timedelta(days=1),
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

        writer = create_rls_engine(writer_dsn)
        reader = create_rls_engine(reader_dsn)
        try:
            # BOTH FAILURE SHAPES REPORT THE SAME WAY. A broken write path either RAISES (no
            # grant, no schema, unreachable) or lands nothing quietly (RLS refusing under a
            # policy that matches no row). The diagnostic below is worth having in either case,
            # so the raising kind is re-raised as this error rather than surfacing as a bare
            # ProgrammingError from inside a fixture.
            try:
                await PostgresActionAppender(writer, PROBE_TENANT_ID).append(probe)
                events = await PostgresActionReader(reader, PROBE_TENANT_ID).events()
            except Exception as exc:
                raise ActionLogNotWritableError(
                    f"the action-log write path RAISED while appending probe {probe.event_id} "
                    f"under tenant {PROBE_TENANT_ID}, so this test cannot prove anything "
                    f"({what}). {_DIAGNOSIS}"
                ) from exc
        finally:
            await writer.dispose()
            await reader.dispose()

        if not any(event.event_id == probe.event_id for event in events):
            raise ActionLogNotWritableError(
                f"appended probe {probe.event_id} to synapse.actions under tenant "
                f"{PROBE_TENANT_ID} and synapse_reader cannot see it among {len(events)} rows - "
                f"the write path is SILENTLY dropping rows, so this test cannot prove anything "
                f"({what}). {_DIAGNOSIS}"
            )
        _PROBE_VERDICT.append(probe.event_id)
        return probe.event_id

    return _require
