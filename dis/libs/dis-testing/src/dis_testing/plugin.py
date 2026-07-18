"""Pytest plugin exposing DIS test fixtures to every service's test suite.

Registered as a pytest11 entry point (see ``pyproject.toml``), so any test suite
with ``dis-testing`` installed gets these fixtures without importing anything.

Fixtures that need the live stack (Postgres / running fakes) **skip** when the
relevant env var is unset or the resource is unreachable, so a bare ``uv run
pytest`` stays green; ``make run-local`` + ``make test`` exercises them for real.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from dis_core.identity import HttpIdentityClient
    from dis_testing.migration_harness import ScratchDB


# Resident-DB fingerprint captured at true session start (Slice 51c, D122). None when no stack
# is configured (POSTGRES_ADMIN_URL unset) so a bare ``pytest`` run stays green.
_RESIDENT_FINGERPRINT: tuple[str, str] | None = None


# ---------------------------------------------------------------------------
# Postgres / seeder
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def dis_postgres_url() -> str:
    url = os.environ.get("POSTGRES_URL")
    if not url:
        pytest.skip("POSTGRES_URL not set — local stack not configured")
    return url


@pytest.fixture(scope="session")
def dis_engine(dis_postgres_url: str) -> Iterator[Engine]:
    from sqlalchemy import create_engine, text

    engine = create_engine(dis_postgres_url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — any connect failure means "stack down → skip"
        engine.dispose()
        pytest.skip(f"DIS Postgres unreachable ({exc!r})")
    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# Migration-test harness (Slice 51c, D122): ephemeral scratch DBs + a read-only
# resident reference. These fixtures live in the plugin (not a repo-root
# tests/integration/conftest.py, which collides with service conftests on the
# pytest module name — see _dis_identity_synced below). Migration tests are
# load-bearing proofs, so the resident-URL fixtures ERROR (never skip) when the
# stack is absent — the Slices 4/7 rule.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def admin_url() -> str:
    """Resident admin URL, asserted to be the DIS DB on 5433 (read-only reference)."""
    from dis_testing.migration_harness import require_admin_url

    return require_admin_url()


@pytest.fixture(scope="module")
def admin_engine(admin_url: str) -> Iterator[Engine]:
    """Read-only engine on the resident DB. Migration tests must NOT drive alembic through it;
    it exists to read the migrated reference schema."""
    from sqlalchemy import create_engine

    engine = create_engine(admin_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def scratch_db(request: pytest.FixtureRequest, admin_url: str) -> Iterator[ScratchDB]:
    """A fresh ephemeral scratch DB, created on the resident server, brought to head via the
    real chain, torn down at test teardown. Every migration upgrade/downgrade cycle runs here,
    never against the resident DB.

    FUNCTION-scoped (not module): tests that drive their own upgrade/downgrade/stamp cycles
    (e.g. the 0008 re-apply idempotency proof) leave the DB off-head, so a shared module DB would
    make sibling tests order-dependent. A pristine at-head DB per test removes that coupling. Its
    name is derived from the test module so concurrent modules do not collide."""
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    from dis_testing.migration_harness import ScratchDB, scratch_env, terminate_and_drop

    parsed = make_url(admin_url)
    module_name = request.module.__name__.rsplit(".", 1)[-1]
    name = f"scratch_{module_name}".lower()[:63]
    scratch_url = parsed.set(database=name)
    scratch_str = scratch_url.render_as_string(hide_password=False)

    server_engine = create_engine(admin_url)  # resident server, for CREATE/DROP only
    try:
        terminate_and_drop(server_engine, name, recreate=True)
        engine = create_engine(scratch_url)
        sdb = ScratchDB(name=name, url=scratch_str, engine=engine, env=scratch_env(scratch_str, name))
        sdb.alembic("upgrade", "head")
        try:
            yield sdb
        finally:
            engine.dispose()
            terminate_and_drop(server_engine, name, recreate=False)
    finally:
        server_engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _dis_identity_synced() -> None:
    """Populate identity_mirror once per session via the REAL mirror-sync path.

    identity_mirror is owned by mirror-sync (Slice 7); the seeder no longer writes
    it. Many tests assume a mirrored tenant/store exists as an FK target (the
    mapping seed, the migration FK tests, the 3 NOBYPASSRLS user-role tests). This
    autouse SESSION fixture runs the sync once, before any module/function fixture
    (so it precedes every ``seed_default_fixtures`` call), uniformly across all test
    groups — so the user-role tests get their FK targets without holding admin
    access themselves. Idempotent (upsert): re-running adds nothing and leaves
    identity_mirror identical. Skip-safe: with no stack env it returns, so a bare
    ``pytest`` stays green. (Replaces a repo-root tests/integration/conftest.py,
    which collided with service conftests on the pytest module name.)
    """
    admin_url = os.environ.get("POSTGRES_ADMIN_URL")
    user_url = os.environ.get("POSTGRES_URL")
    if not (admin_url and user_url):
        # Both absent = no stack: stay silent so a bare `pytest` collection/run is green.
        # Partial env (POSTGRES_URL set, POSTGRES_ADMIN_URL missing) is the dangerous case:
        # the sync is skipped here, but stack-needing tests will still try to seed
        # config.source_mappings and fail with an obscure fk_csm_tenant error. Surface the
        # real reason loudly so the failure is self-explaining, not a confusing FK trace.
        if user_url and not admin_url:
            warnings.warn(
                "identity_mirror sync SKIPPED: POSTGRES_ADMIN_URL is not set but POSTGRES_URL is. "
                "Integration tests that need FK targets (the mapping seed, the user-role tests) "
                "will fail with a config.source_mappings fk_csm_tenant error. Set "
                "POSTGRES_ADMIN_URL (e.g. run via `make test`, which exports .env), or unset "
                "POSTGRES_URL to skip the stack tests cleanly.",
                stacklevel=2,
            )
        return
    from dis_testing.identity_sync import sync_identity_mirror

    sync_identity_mirror(admin_url, user_url)


# D100 post-suite clean-state guard: the prototype assertion was removed when resident workers
# could write rows no test owned (shared Pub/Sub subscriptions); the emulator-project isolation
# below (pytest_configure + _dis_pubsub_provisioned) closed that. The guard is RE-ENABLED below as
# ``pytest_sessionfinish`` — see ``_assert_clean_shared_db_after_suite`` and decisions.md D100.
# ``identity_mirror`` is EXCLUDED from the guard: the resident mirror-sync co-populates it from the
# REAL Customer Master (a variable, non-test baseline — 7 tenants / 25 stores locally), so it has
# no test-vs-baseline discriminator. The standing rule holds: a test that mutates the shared DB
# reverts its own writes (the cleanup idiom); the guard asserts that END state.


def pytest_configure() -> None:
    """Route the pytest process onto the test-scoped Pub/Sub project (D100 isolation).

    Runs before any test module is imported, so module-level project reads and every
    in-process service config (dis-ui-server's ``create_app``) resolve the test project
    from ``PUBSUB_PROJECT_ID``. Gated on ``PUBSUB_EMULATOR_HOST``: a bare run with no
    stack is untouched (unit tests set their own ``PUBSUB_PROJECT_ID``; integration tests
    skip via their stack-required fixtures). Residents are SEPARATE processes started with
    ``.env``'s local-dis, so this in-process override cannot reach them — the isolation is
    structural, not a convention.
    """
    if os.environ.get("PUBSUB_EMULATOR_HOST"):
        from dis_testing.pubsub import TEST_PUBSUB_PROJECT_ID

        # Record the stack project (residents + docker containers, e.g. the CM fake)
        # BEFORE redirecting in-process test code, so a test that interoperates with a
        # stack process can still target it (pubsub_stack_project). setdefault keeps it
        # stable across re-entry.
        os.environ.setdefault("DIS_STACK_PUBSUB_PROJECT_ID", os.environ.get("PUBSUB_PROJECT_ID", "local-dis"))
        os.environ["PUBSUB_PROJECT_ID"] = TEST_PUBSUB_PROJECT_ID


def pytest_sessionstart(session: pytest.Session) -> None:
    """Snapshot the resident DB (alembic_version + schema fingerprint) at TRUE session start,
    before any test/fixture touches it (Slice 51c, D122, AC1).

    Fail-loud, never skip: when the stack is configured (``POSTGRES_ADMIN_URL`` set) the snapshot
    MUST capture — if the resident DB is unreachable or has no ``alembic_version``, the error
    propagates and aborts the session (a partial/late snapshot would give a false pass). When no
    stack is configured, stay silent so a bare ``pytest`` run is green — there is no resident DB
    to protect, and migration tests fail loud on their own stack-required fixtures.
    """
    global _RESIDENT_FINGERPRINT
    admin_url = os.environ.get("POSTGRES_ADMIN_URL")
    if not admin_url:
        return
    from sqlalchemy import create_engine

    from dis_testing.migration_harness import resident_fingerprint

    engine = create_engine(admin_url)
    try:
        _RESIDENT_FINGERPRINT = resident_fingerprint(engine)
    finally:
        engine.dispose()


def _assert_resident_untouched(admin_url: str) -> None:
    """Assert the resident DB's schema/version is byte-identical to the session-start snapshot
    (Slice 51c, D122, AC1). Any migration test that targeted the resident DB (5433) instead of a
    scratch DB shows up here as a schema/version drift."""
    from sqlalchemy import create_engine

    from dis_testing.migration_harness import resident_fingerprint

    engine = create_engine(admin_url)
    try:
        after = resident_fingerprint(engine)
    finally:
        engine.dispose()
    if after != _RESIDENT_FINGERPRINT:
        report = (
            "Resident-untouched guard FAILED (Slice 51c, AC1) — the resident dev DB (5433) "
            "schema/version changed during the run. A migration test targeted the resident DB "
            f"instead of an ephemeral scratch DB.\n  before={_RESIDENT_FINGERPRINT}\n  after={after}"
        )
        print(f"\n{report}", flush=True)  # noqa: T201 — surface the report above the raise
        raise AssertionError(report)


@pytest.fixture(scope="session", autouse=True)
def _dis_pubsub_provisioned() -> None:
    """Provision the test-scoped project's topics + standing subscriptions (D100).

    The same name set tools/local/create_topics.py provisions on local-dis, but on the
    test project, so the in-process subscribers' startup existence check finds their
    subscription. Idempotent (AlreadyExists-safe) and skip-safe: with no emulator env it
    returns, so a bare ``pytest`` stays green.
    """
    if not os.environ.get("PUBSUB_EMULATOR_HOST"):
        return
    from dis_core.pubsub_names import provision_pubsub
    from dis_testing.pubsub import TEST_PUBSUB_PROJECT_ID

    provision_pubsub(TEST_PUBSUB_PROJECT_ID)


# ---------------------------------------------------------------------------
# D100 post-suite clean-state guard
# ---------------------------------------------------------------------------
# Tables whose post-suite baseline is EMPTY on a freshly-reset stack: any row is
# residue. All carry ``trace_id`` NOT NULL — the per-ingress discriminator the guard
# reports so a failure names the leaking flow. ``signal_history`` is daily-compute
# output with no cleanup fixture (D31/D32); it is intentionally in this set, so the
# guard fires if a future compute-path test ever writes it unreverted. The four
# ``staging.*`` tables mirror ``canonical.*`` (migration 0009) and are test-writable
# (the 0009 de-partition tests write ``staging.store_sku_change_events``); they carry
# ``trace_id`` too, so the same COUNT==0 + trace_id check covers them verbatim.
_D100_EMPTY_TABLES: tuple[str, ...] = (
    "audit.events",
    "bronze.data_ingress_events",
    "canonical.store_sku_current_position",
    "canonical.store_sku_sale_events",
    "canonical.store_sku_change_events",
    "canonical.store_sku_signal_history",
    "staging.store_sku_current_position",
    "staging.store_sku_sale_events",
    "staging.store_sku_change_events",
    "staging.store_sku_signal_history",
    "quarantine.quarantined_chunks",
    "quarantine.quarantined_rows",
)


class SuiteResidueError(AssertionError):
    """A test left residue in the shared dev DB (D100 post-suite clean-state guard)."""


def _assert_clean_shared_db_after_suite(admin_url: str) -> None:
    """Fail loud if the test SUITE left residue in the shared DB (D100, post-suite).

    Contract: this asserts the SUITE leaves no residue *starting from a clean reset*
    (``make reset-local`` -> ``make run-local`` -> ``make test``). It does NOT police
    accumulated operator/resident artifacts on a long-lived un-reset box (pipeline-check
    scripts, manual pipeline runs) — those are not test residue and a reset clears them.

    Reads via the ADMIN engine (``POSTGRES_ADMIN_URL``, role ``ithina_dis_admin`` =
    superuser), which bypasses FORCE RLS so the guard sees true state across all tenants
    — a NOBYPASSRLS session would read RLS-empty and pass FALSELY. The seeded-mapping
    baseline comes from the SAME fixture constants the seeder uses
    (``fx.DEFAULT_SOURCE_MAPPING``) so guard and seed cannot drift; the mapping is matched
    by (tenant, source, template), NEVER by ``mapping_version_id`` (an unstable BIGSERIAL).

    ``identity_mirror`` is intentionally NOT checked: the resident mirror-sync co-populates
    it from the real Customer Master (a variable, non-test baseline — 7 tenants / 25 stores
    locally), so it has no test-vs-baseline discriminator; test edge-stores are reverted by
    their own teardowns. Raises :class:`SuiteResidueError` naming every leaker.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from dis_testing import fixtures as fx

    url = make_url(admin_url)
    # Target safety (mirrors the dis_admin fixture in the service conftests): only ever
    # read the local DIS dev DB, never a real database.
    assert url.database == "ithina_dis_db", f"D100 guard: refusing DB {url.database!r}"
    assert url.port == 5433, f"D100 guard: refusing port {url.port!r}"

    findings: list[str] = []
    engine = create_engine(admin_url)
    try:
        with engine.connect() as conn:
            # 1. Empty-baseline tables: any row is residue; report trace_ids.
            for table in _D100_EMPTY_TABLES:
                total = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                if not total:
                    continue
                traces = conn.execute(text(f"SELECT trace_id FROM {table} LIMIT 20")).fetchall()
                shown = ", ".join(str(row[0]) for row in traces)
                more = "" if total <= len(traces) else f" (+{total - len(traces)} more)"
                findings.append(f"{table}: {total} residue row(s); trace_ids=[{shown}]{more}")

            # 2. config.source_mappings: a baseline-COMPLETENESS check — the table must
            #    contain EXACTLY the seeded baseline and nothing else. Baseline triples are
            #    derived from the seeder's fixture constant (fx.DEFAULT_SOURCE_MAPPING; one
            #    row today) so the check tracks the seed if it grows. Matched by
            #    (tenant, source, template), NEVER mapping_version_id. This is a count-per-
            #    triple test, not row-membership: a SECOND row sharing a baseline triple
            #    (extra version_seq / duplicate ACTIVE / DEPRECATED prior) is residue too.
            seeded = fx.DEFAULT_SOURCE_MAPPING
            baseline_triples = {
                (
                    str(fx.tenant_uuid_for(str(seeded["tenant_display_code"]))),
                    str(seeded["source_id"]),
                    str(seeded["template_id"]),
                )
            }
            counts: dict[tuple[str, str, str], int] = {}
            problems: list[str] = []
            for row in conn.execute(
                text("SELECT tenant_id::text, source_id, template_id::text FROM config.source_mappings")
            ).fetchall():
                triple = (str(row[0]), str(row[1]), str(row[2]))
                if triple in baseline_triples:
                    counts[triple] = counts.get(triple, 0) + 1
                else:
                    problems.append(f"source_id={row[1]!r}(tenant {row[0]}) [non-baseline]")
            for triple, count in counts.items():
                if count > 1:
                    problems.append(
                        f"source_id={triple[1]!r}(tenant {triple[0]}) "
                        f"[{count} rows share one baseline triple]"
                    )
            if problems:
                findings.append(f"config.source_mappings: {len(problems)} issue(s); " + ", ".join(problems))
    finally:
        engine.dispose()

    if findings:
        report = (
            "D100 post-suite clean-state guard FAILED — the test suite left residue in the shared "
            "DB (a test that mutates the shared DB must revert its own writes):\n  " + "\n  ".join(findings)
        )
        print(f"\n{report}", flush=True)  # noqa: T201 — surface the report above the raise
        raise SuiteResidueError(report)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """After the whole suite (post-teardown), assert the suite left no shared-DB residue (D100).

    Two independent post-suite guards run here:
      * Resident-untouched (Slice 51c, D122, AC1): fires whenever ``POSTGRES_ADMIN_URL`` is set
        and a start-snapshot was captured — independent of the pubsub gate.
      * D100 post-suite clean-state: gated on ``PUBSUB_EMULATOR_HOST`` (the isolation gate).

    Both return silently if ``POSTGRES_ADMIN_URL`` is absent. Runs at session finish, so every
    per-test cleanup has already executed — the guards assert that END state.
    """
    admin_url = os.environ.get("POSTGRES_ADMIN_URL")
    if not admin_url:
        return
    if os.environ.get("PUBSUB_EMULATOR_HOST"):
        _assert_clean_shared_db_after_suite(admin_url)
    if _RESIDENT_FINGERPRINT is not None:
        _assert_resident_untouched(admin_url)


@pytest.fixture(scope="session")
def seeded_identity(dis_engine: Engine, dis_postgres_url: str) -> Engine:
    """Sync identity_mirror (mirror-sync owns it) then seed the default mapping.

    identity_mirror is owned by mirror-sync; the seeder only writes
    config.source_mappings and requires the tenant FK target to already exist.
    Needs POSTGRES_ADMIN_URL to provision/sync the test-CM stand-in; skip if the
    full admin stack is absent (a bare run never reaches here anyway).
    """
    admin_url = os.environ.get("POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("POSTGRES_ADMIN_URL not set — cannot sync identity_mirror before seeding")

    from dis_testing.identity_sync import sync_identity_mirror
    from dis_testing.seed import seed_default_fixtures

    sync_identity_mirror(admin_url, dis_postgres_url)
    seed_default_fixtures(engine=dis_engine)
    return dis_engine


# ---------------------------------------------------------------------------
# Running fakes (HTTP)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def identity_service_url() -> str:
    url = os.environ.get("IDENTITY_SERVICE_URL")
    if not url:
        pytest.skip("IDENTITY_SERVICE_URL not set — identity-service fake not configured")
    return url


@pytest.fixture(scope="session")
def customer_master_url() -> str:
    url = os.environ.get("CUSTOMER_MASTER_URL")
    if not url:
        pytest.skip("CUSTOMER_MASTER_URL not set — customer-master fake not configured")
    return url


@pytest.fixture
async def identity_client(identity_service_url: str) -> AsyncIterator[HttpIdentityClient]:
    """An ``HttpIdentityClient`` pointed at the running Identity Service fake.

    This is the same client real consumers use; the Slice 13 service is a drop-in
    behind the same ``IDENTITY_SERVICE_URL`` (acceptance criterion 8).
    """

    from dis_core.identity import HttpIdentityClient

    _ensure_reachable(f"{identity_service_url}/healthz")
    client = HttpIdentityClient(identity_service_url)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def cm_jwt(customer_master_url: str) -> str:
    """A signed JWT obtained from the running Customer Master fake."""
    import httpx

    _ensure_reachable(f"{customer_master_url}/healthz")
    resp = httpx.post(f"{customer_master_url}/v1/tokens", json={}, timeout=5.0)
    resp.raise_for_status()
    token: str = resp.json()["jwt"]  # JSON boundary -> declared str
    return token


def _ensure_reachable(health_url: str) -> None:
    import httpx

    try:
        httpx.get(health_url, timeout=2.0).raise_for_status()
    except Exception as exc:  # noqa: BLE001 — fake not up → skip the test
        pytest.skip(f"fake not reachable at {health_url} ({exc!r})")
