"""Shared vacuity guard for Synapse's live tests, and how to run them at all.

THERE ARE TWO KINDS OF TEST IN HERE AND THEY RUN AGAINST DIFFERENT DATABASES.

- The five RESOLVER tests are read-only and want REAL DATA, so they run against staging with
  ``SYNAPSE_READER_URL``. They cannot pollute anything: ``synapse_reader`` holds SELECT and
  nothing else, by grant rather than by convention.
- The two WRITE modules (``test_action_log_live``, ``test_orchestrator_live``) append to
  ``synapse.actions``, which is APPEND-ONLY — the trigger refuses DELETE for every role
  including the owner, so a fixture row written to staging is permanent. They are REFUSED
  against the real database outright; see ``assert_disposable``. They run against a disposable
  database this file builds.

HOW TO RUN THE WRITE TESTS — one copy-pasteable invocation. The database does not need to
exist; the ``disposable_database`` fixture drops, clones and migrates it at session start.

    cd dis && \\
      DB=synapse_test && AT=localhost:5433/$DB && P=postgresql+psycopg && \\
      SYNAPSE_ADMIN_URL="$P://ithina_dis_admin:ithina_dis_admin_password@$AT" \\
      SYNAPSE_WRITER_URL="$P://synapse_writer:synapse_writer_password@$AT" \\
      SYNAPSE_READER_URL="$P://synapse_reader:synapse_reader_password@$AT" \\
      DIS_EXPECTED_DATABASE=$DB \\
      uv run pytest -c pyproject.toml -p no:dis_testing \\
        ../synapse/tests/integration/test_action_log_live.py \\
        ../synapse/tests/integration/test_orchestrator_live.py

ALL FOUR NAME THE SAME DATABASE, and that is forced rather than tidy: ``dis_rls`` resolves ONE
``_EXPECTED_DATABASE`` at import and refuses every connection to any other name, so the reader
and writer engines cannot be split across two databases in one process. Trying it fails with
``RlsContextError``, which reads as a typo rather than as a structural limit.

Inspect the wreckage afterwards with ``psql -d synapse_test`` — and SET THE GUCs when you do,
or FORCE RLS reports 0 rows for a healthy log and an empty one alike. Nothing needs cleaning
up; the next run drops it.

HOW TO RUN THE RESOLVER TESTS AGAINST STAGING — the whole invocation, in one copy-pasteable
place, because it has four requirements and three of them fail in ways that do not name
themselves.

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

FIXTURES WHERE A FIXTURE WORKS, ONE IMPORTABLE HELPER WHERE IT CANNOT. The vacuity guards are
fixtures. ``assert_disposable`` cannot be: it has to run at COLLECTION time, before any engine
exists, and a fixture runs too late to stop a module-scope DSN from being used. So this package
gained the three ``__init__.py`` files that ``services/streaming-consumer/tests/`` already has,
and the two write modules import it with ``from .conftest import`` — the same relative form used
in 17 places there. Under ``--import-mode=importlib`` a BARE ``from conftest import`` raises
ModuleNotFoundError at collection and takes the whole file down; the package markers are what
make the relative form resolve. Shared rather than copied per file because two byte-identical
guards in one directory is how the duplicated Pub/Sub poll loop started, and that is already a
ledger item.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit
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


# ===========================================================================================
# THE DISPOSABLE-DATABASE GUARD
# ===========================================================================================
# WHY THIS IS STRUCTURE AND NOT A CONVENTION. The live write tests append to
# ``synapse.actions``, which is APPEND-ONLY: the trigger refuses DELETE for every role including
# the owner, so a fixture row written to the real database is IMMORTAL. Thirteen of them already
# sit in staging, minted by earlier runs — each run coins fresh UUIDs (PROBE-{uuid4},
# SKU-BASELINE-{uuid4}, SKU-IDEMPOTENCY-{uuid4}) rather than colliding with the last, so the row
# count only ever grows. Those thirteen stay; they are invisible to tenant views through RLS.
# This stops the growth.
#
# A COMMENT SAYING "point this at a scratch database" WOULD NOT HAVE PREVENTED THEM. The DSNs
# come from the environment, and the environment on an operator's machine is the staging one,
# because that is what every other task needs. So the refusal is code, it runs at COLLECTION
# time before any engine is built, and it FAILS rather than skips — a skipped guard is
# indistinguishable from a guard that never ran, which is a failure mode this project has
# already paid for.
#
# TWO INDEPENDENT CHECKS, because either alone is escapable:
#   - dbname ``thalamus``      catches the real database under any host or alias
#   - host 10.55.0.3           catches the real INSTANCE whatever database is named, so a
#                              second real database created later is refused without anyone
#                              remembering to add it here
_FORBIDDEN_DBNAMES = frozenset({"thalamus"})
_FORBIDDEN_HOSTS = frozenset({"10.55.0.3"})


def _describe(dsn: str) -> str:
    """host/dbname only. NEVER the DSN — it carries the password and this string reaches pytest
    output, which reaches CI logs."""
    parts = urlsplit(dsn)
    return f"host={parts.hostname or '?'} dbname={(parts.path or '/').lstrip('/') or '?'}"


def assert_disposable(dsn: str | None, *, var: str) -> None:
    """Refuse a write DSN that points at real staging. No-op when the DSN is unset.

    Unset is fine — the tests skip, which is the honest outcome for an unarmed run. What must
    never happen is an ARMED run against the real ledger.
    """
    if not dsn:
        return
    parts = urlsplit(dsn)
    dbname = (parts.path or "/").lstrip("/").split("?")[0]
    host = parts.hostname or ""
    if dbname in _FORBIDDEN_DBNAMES or host in _FORBIDDEN_HOSTS:
        raise RuntimeError(
            f"{var} points at real staging ({_describe(dsn)}) and the live write tests refuse "
            "to run against it. synapse.actions is append-only: every fixture row they write "
            "would be permanent, and thirteen such rows already exist from before this guard.\n\n"
            "Point the write DSNs at a DISPOSABLE database — see this file's header for the "
            "harness. Reads are unaffected: SYNAPSE_READER_URL may stay on staging, because the "
            "reader role cannot write."
        )


# ===========================================================================================
# THE DISPOSABLE DATABASE ITSELF
# ===========================================================================================
# The guard above says where the write tests may NOT run. This builds the place they may.
#
# WHY IT IS BUILT FROM THE ALEMBIC CHAIN AND NOT FROM schemas/postgres/*.sql. Applying the DDL
# directly would produce a database that no environment has ever had: the chain is what runs
# against staging, so the chain is what the tests must run against. If 0002's reset or 0004's
# ADD COLUMN is wrong, a DDL-built harness passes and staging breaks — the test bed would be
# proving a schema nobody deploys. The DDL is still the source of truth for CONTENT; 0001 reads
# actions.sql verbatim. This just refuses to take the shortcut past the applier.
#
# WHAT THE CHAIN DOES NOT BRING, and therefore what this fixture adds:
#   - THE ROLES. `GRANT ... TO synapse_writer` is an error if the role is absent, and roles are
#     cluster-wide rather than per-database. The local devbox has synapse_reader but NOT
#     synapse_writer (postgres-init.sql grew it after the volume was created), so a devbox that
#     has never been wiped fails on migration 0001 without this.
#   - CANONICAL. Synapse READS canonical and writes synapse; the orchestrator opens both engines
#     in one process. That cannot be split across two databases, and the reason is worth writing
#     down because it is invisible until it bites: ``dis_rls`` resolves ONE ``_EXPECTED_DATABASE``
#     at import and refuses every connection to any other name. Point the reader at the devbox
#     and the writer at a scratch database and the writer fails with ``RlsContextError``, which
#     reads as a config mistake rather than as a structural constraint.
#
#     So the disposable database is CREATE DATABASE ... TEMPLATE of the local DIS database: it
#     arrives with canonical's real DDL, grants and RLS policies rather than a hand-written
#     lookalike that would drift the moment canonical changes. One database, one expected name,
#     both engines satisfied.
#
#     A BARE STUB IS THE FALLBACK when no template is available. One test asserts the writer
#     holds nothing on canonical; against a database where that table is MISSING the failure is
#     "relation does not exist" — a pass for a test looking only for an exception, proving
#     nothing about grants. The table must EXIST and be unreachable.
#
# THIS DOES NOT MANUFACTURE CANONICAL ROWS, and must not. The vacuity guards above exist because
# row-dependent tests are worthless against an empty table, and a harness that seeded canonical
# would be the first crack in a read-only plane. A devbox with no residue makes the data-dependent
# tests RAISE, which is the honest outcome — not something for this fixture to paper over.
#
# IT IS REBUILT AT SESSION START, NOT TORN DOWN AT SESSION END. Dropping afterwards would leave
# nothing to inspect after a failure, which is when inspection matters. Dropping FIRST gets the
# same pristine bed and keeps the wreckage.

_DISPOSABLE_ROLES = ("synapse_writer", "synapse_reader")

# THE ONE TABLE IN THIS SCHEMA THAT MUST NOT HAVE RLS, and the reason is a trap rather than an
# exception. synapse.quarantined_tenants LISTS tenants; it is not OWNED by one, so there is no
# tenant_id for a policy to compare and no meaningful scoping.
#
# Worse than meaningless — ACTIVELY HARMFUL. synapse.actions_analytical is security_invoker, so
# its anti-join runs with the querying role's rights. If RLS hid the registry's rows from that
# session, NOT EXISTS would find nothing and the view would return EVERY row including the
# quarantined ones. The quarantine would fail OPEN, look correct, and be discovered by a model
# trained on fixtures.
_NO_RLS_BY_DESIGN = frozenset({"quarantined_tenants"})

# The database the disposable one is cloned from. Its own name is never written to.
_TEMPLATE_DB = os.environ.get("SYNAPSE_DISPOSABLE_TEMPLATE", "ithina_dis_db")


def _maintenance_dsn(dsn: str) -> tuple[str, str]:
    """Split a target DSN into (libpq DSN for the `postgres` maintenance db, target dbname)."""
    parts = urlsplit(dsn)
    dbname = (parts.path or "/").lstrip("/").split("?")[0]
    userinfo = f"{parts.username}:{parts.password}@" if parts.username else ""
    netloc = f"{userinfo}{parts.hostname}:{parts.port or 5432}"
    return urlunsplit(("postgresql", netloc, "/postgres", "", "")), dbname


def _provision_disposable(admin_dsn: str) -> str:
    """Drop, recreate and migrate the disposable database. Returns its name.

    Synchronous psycopg on purpose: this runs once at session start, before any engine exists,
    and CREATE DATABASE cannot run inside a transaction block.
    """
    import subprocess
    import sys

    import psycopg

    maintenance, dbname = _maintenance_dsn(admin_dsn)
    if not dbname:
        raise RuntimeError(f"SYNAPSE_ADMIN_URL names no database ({_describe(admin_dsn)})")

    with psycopg.connect(maintenance, autocommit=True) as conn:
        # The roles first: cluster-wide, so this is idempotent across databases and runs.
        # NOSUPERUSER NOBYPASSRLS is not decoration — a bypassrls role turns every RLS
        # assertion below into a tautology, which is the "superuser repro proves nothing"
        # trap this project has already hit.
        for role in _DISPOSABLE_ROLES:
            conn.execute(
                f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') "
                f"THEN CREATE ROLE {role} WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB "
                f"NOCREATEROLE PASSWORD '{role}_password'; END IF; END $$;"
            )
        conn.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')
        template = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (_TEMPLATE_DB,)).fetchone()
        if template:
            # WITH (FORCE) above, and this next line, both need the TEMPLATE to be idle:
            # postgres refuses to clone a database that has open connections. The error names
            # the template rather than this call, so it is re-raised with the cause attached.
            try:
                conn.execute(f'CREATE DATABASE "{dbname}" TEMPLATE "{_TEMPLATE_DB}"')
            except psycopg.errors.ObjectInUse as exc:
                raise RuntimeError(
                    f"cannot clone {_TEMPLATE_DB!r} into the disposable database while something "
                    f"is connected to it. Close other psql/pytest sessions, or set "
                    f"SYNAPSE_DISPOSABLE_TEMPLATE to a quiet database."
                ) from exc
        else:
            conn.execute(f'CREATE DATABASE "{dbname}"')

    with psycopg.connect(maintenance.replace("/postgres", f"/{dbname}"), autocommit=True) as conn:
        for role in _DISPOSABLE_ROLES:
            conn.execute(f'GRANT CONNECT ON DATABASE "{dbname}" TO {role}')
        # The clone carries whatever synapse schema the template had, and the chain is not
        # idempotent against an existing one. Start it from nothing so 0001..0004 all really run.
        conn.execute("DROP SCHEMA IF EXISTS synapse CASCADE")
        conn.execute("DROP TABLE IF EXISTS synapse_alembic_version")
        if not template:
            # Fallback stub: columns are irrelevant, the test must be denied before reading one.
            # No grants, deliberately.
            conn.execute("CREATE SCHEMA IF NOT EXISTS canonical")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS canonical.store_sku_current_position "
                "(tenant_id uuid NOT NULL, sku_id text NOT NULL)"
            )

    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=root,
        env={**os.environ, "SYNAPSE_ADMIN_URL": admin_dsn},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"the alembic chain failed against the disposable database "
            f"({_describe(admin_dsn)}):\n{result.stdout}\n{result.stderr}"
        )
    return dbname


def _verify_disposable(admin_dsn: str) -> None:
    """Refuse a permissive lookalike.

    WITHOUT THIS THE HARNESS IS THE VACUITY BUG IT EXISTS TO AVOID. Every write-side test here
    is a REFUSAL test — cross-tenant append denied, read-only role denied, UPDATE denied — and a
    refusal test passes when nothing works. It would also pass on a database with RLS merely
    ENABLED rather than FORCED (the owner bypasses it), or against a role carrying rolbypassrls.
    Both produce a green suite that has verified nothing about isolation.
    """
    import psycopg

    with psycopg.connect(admin_dsn.replace("postgresql+psycopg://", "postgresql://")) as conn:
        forced = conn.execute(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'synapse' "
            "AND c.relkind = 'r' ORDER BY c.relname"
        ).fetchall()
        if not forced:
            raise RuntimeError("the disposable database has no synapse tables; the chain did not run")
        # THE ONE TABLE IN THIS SCHEMA THAT MUST NOT HAVE RLS, and the reason is a trap rather
        # than an exception. synapse.quarantined_tenants LISTS tenants; it is not OWNED by one,
        # so there is no tenant_id for a policy to compare and no meaningful scoping.
        #
        # Worse than meaningless — ACTIVELY HARMFUL. synapse.actions_analytical is
        # security_invoker, so its anti-join runs with the querying role's rights. If RLS hid the
        # registry's rows from that session, NOT EXISTS would find nothing and the view would
        # return EVERY row including the quarantined ones. The quarantine would fail OPEN, look
        # correct, and be discovered by a model trained on fixtures.
        weak = [
            name
            for name, enabled, force in forced
            if not (enabled and force) and name not in _NO_RLS_BY_DESIGN
        ]
        if weak:
            raise RuntimeError(
                f"synapse tables without FORCE ROW LEVEL SECURITY on the disposable database: "
                f"{weak}. Every write-side test is a refusal test and would pass regardless."
            )
        policies = conn.execute("SELECT tablename FROM pg_policies WHERE schemaname = 'synapse'").fetchall()
        missing = {name for name, _, _ in forced} - {t for (t,) in policies} - _NO_RLS_BY_DESIGN
        if missing:
            raise RuntimeError(f"synapse tables with FORCE RLS but no policy: {sorted(missing)}")
        loose = conn.execute(
            "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s) AND (rolsuper OR rolbypassrls)",
            (list(_DISPOSABLE_ROLES),),
        ).fetchall()
        if loose:
            raise RuntimeError(
                f"role(s) {[r for (r,) in loose]} carry rolsuper/rolbypassrls, so RLS does not "
                "apply to them and every isolation assertion here is vacuous."
            )


@pytest.fixture(scope="session", autouse=True)
def disposable_database() -> str | None:
    """Build the write tests a database of their own. No-op for an unarmed or read-only run.

    Autouse and session-scoped: the read-only resolver tests in this directory take no write DSN
    and are untouched, and an unarmed run does nothing at all.
    """
    admin_dsn = os.environ.get("SYNAPSE_ADMIN_URL")
    if not admin_dsn:
        return None
    assert_disposable(admin_dsn, var="SYNAPSE_ADMIN_URL")
    dbname = _provision_disposable(admin_dsn)
    _verify_disposable(admin_dsn)
    return dbname


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
