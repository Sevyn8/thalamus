"""Migration 0007 against a REAL Postgres, with quarantined AND real rows in the table.

THE ASSERTION THAT MATTERS is not "the view exists" — it is "the view excludes EXACTLY the
quarantined tenant and nothing else". A view that returns nothing passes every exclusion check
ever written, so both sides have to be populated: probe rows under the registered tenant, and
real rows under a tenant that is not registered. That mirrors staging, where thirteen fixtures
sit alongside the Body Shop's three genuine actions.

IT ALREADY EARNED ITS PLACE. The first execution of 0007 died with ``syntax error at or near
"s"``: the seeded provenance note says "slice 9's alert emission", and an apostrophe inside a
single-quoted SQL literal ends the string. That is the SAME failure 0005 shipped to staging with,
in a different migration, four revisions later — caught here instead of there. The fix was bound
parameters rather than doubled quotes, which removes the class instead of the instance.

WHAT THIS CANNOT PROVE, stated so nobody reads it as more than it is: that the SEEDED id matches
the thirteen rows in staging. A disposable database has no probe rows, so the seed's correctness
is only observable against staging — see the migration header, and the post-apply Studio check in
the slice report. This file proves the MECHANISM; the seed is verified by counting.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest

from .conftest import assert_disposable

ADMIN_DSN = os.environ.get("SYNAPSE_ADMIN_URL")

assert_disposable(ADMIN_DSN, var="SYNAPSE_ADMIN_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not ADMIN_DSN,
        reason="needs SYNAPSE_ADMIN_URL pointing at a DISPOSABLE database; see conftest's header",
    ),
]

_ROOT = Path(__file__).resolve().parents[2]

# The seeded sentinel, and a tenant standing in for the Body Shop's real rows.
_QUARANTINED = "decafbad-0000-4000-8000-000000000001"
_REAL = "019fb16b-e402-7dce-b026-6fa9f4919242"
_STORE = "019fb16b-0000-7000-8000-0000000000aa"


def _libpq(dsn: str, dbname: str) -> str:
    parts = urlsplit(dsn)
    userinfo = f"{parts.username}:{parts.password}@" if parts.username else ""
    return urlunsplit(
        ("postgresql", f"{userinfo}{parts.hostname}:{parts.port or 5432}", f"/{dbname}", "", "")
    )


def _alembic(dsn: str, revision: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", revision],
        cwd=_ROOT,
        env={**os.environ, "SYNAPSE_ADMIN_URL": dsn},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"alembic upgrade {revision} failed:\n{result.stdout}\n{result.stderr}")


def _as_tenant(conn: psycopg.Connection[object], tenant: str) -> None:
    """Both GUCs. synapse.actions is FORCE RLS and WITH CHECK pins the insert to the session's
    tenant, so this is required even as the owner — and without it a SELECT returns zero rows
    while raising nothing."""
    conn.execute("SELECT set_config('app.user_type', 'TENANT', false)")
    conn.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant,))


def _as_platform(conn: psycopg.Connection[object]) -> None:
    conn.execute("SELECT set_config('app.user_type', 'PLATFORM', false)")
    conn.execute("SELECT set_config('app.tenant_id', '', false)")


def _append(conn: psycopg.Connection[object], tenant: str, sku: str) -> None:
    """One action, the minimum synapse.actions will accept."""
    conn.execute(
        """
        INSERT INTO synapse.actions (
            event_id, recorded_at, target, verb, quantity_at_stake, expires_on, arm,
            declaration_id, declaration_version, capability_versions, thresholds, as_of,
            payload_hash
        ) VALUES (
            gen_random_uuid(), now(),
            CAST(%s AS jsonb), 'review', 1, DATE '2026-12-31', 'treatment',
            -- capability_versions and thresholds are CHECK-constrained non-empty: an action
            -- whose provenance is blank is not analysable, which is the point of both columns.
            'dead_stock', '0.1.0', '{"current_state": "0.1.0"}'::jsonb,
            '{"stale_after_days": 90}'::jsonb, DATE '2026-08-05',
            md5(%s)
        )
        """,
        # store_id is a STORED GENERATED column cast to uuid, so it must parse as one.
        (f'{{"tenant_id": "{tenant}", "store_id": "{_STORE}", "sku_id": "{sku}"}}', sku),
    )


@pytest.fixture
def at_head() -> Iterator[str]:
    """A scratch database at head, holding three probe rows and two real ones.

    BOTH SIDES POPULATED, deliberately: an exclusion asserted against a table containing only
    quarantined rows cannot tell "excluded correctly" from "returned nothing".
    """
    assert ADMIN_DSN is not None
    name = f"synapse_mig7_{uuid4().hex[:12]}"
    maintenance = _libpq(ADMIN_DSN, "postgres")
    template = os.environ.get("SYNAPSE_DISPOSABLE_TEMPLATE", "ithina_dis_db")

    with psycopg.connect(maintenance, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template}"')
    scratch = _libpq(ADMIN_DSN, name)
    try:
        with psycopg.connect(scratch, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS synapse CASCADE")
            conn.execute("DROP TABLE IF EXISTS synapse_alembic_version")

        _alembic(f"postgresql+psycopg://{scratch.split('://', 1)[1]}", "head")

        with psycopg.connect(scratch, autocommit=True) as conn:
            _as_tenant(conn, _QUARANTINED)
            for sku in ("PROBE-aaa", "SKU-IDEMPO-bbb", "SKU-BASELIN-ccc"):
                _append(conn, _QUARANTINED, sku)
        with psycopg.connect(scratch, autocommit=True) as conn:
            _as_tenant(conn, _REAL)
            for sku in ("SKU-0029", "SKU-0031"):
                _append(conn, _REAL, sku)
        yield scratch
    finally:
        with psycopg.connect(maintenance, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _skus(scratch: str, relation: str) -> set[str]:
    with psycopg.connect(scratch) as conn:
        _as_platform(conn)
        return {row[0] for row in conn.execute(f"SELECT sku_id FROM {relation}")}  # noqa: S608


def test_the_fixture_populated_both_sides(at_head: str) -> None:
    """VACUITY GUARD. Every assertion below is about a table holding rows of both kinds."""
    base = _skus(at_head, "synapse.actions")
    assert len(base) == 5, f"expected 3 probe + 2 real, got {sorted(base)}"


def test_the_registry_is_seeded_by_the_migration(at_head: str) -> None:
    """The row's existence is exactly as old as the mechanism, so a fresh database must arrive
    with it — otherwise a new environment silently disagrees with staging about what is real."""
    with psycopg.connect(at_head) as conn:
        rows = conn.execute(
            "SELECT tenant_id::text, reason, registered_by, length(note) FROM synapse.quarantined_tenants"
        ).fetchall()
    assert len(rows) == 1
    tenant, reason, registered_by, note_length = rows[0]
    assert tenant == _QUARANTINED
    assert reason == "test_fixture"
    assert registered_by == "migration 0007"
    assert note_length >= 200, "the provenance note is the reason the registry exists"


def test_the_view_excludes_exactly_the_quarantined_tenant(at_head: str) -> None:
    """THE WHOLE POINT, and it is two assertions rather than one: the probe rows are gone AND the
    real rows survive. Either alone passes against a broken view."""
    analytical = _skus(at_head, "synapse.actions_analytical")

    assert analytical == {"SKU-0029", "SKU-0031"}, (
        f"the analytical view returned {sorted(analytical)}; it must drop the three probe SKUs "
        "and keep both real ones"
    )


def test_the_base_table_still_holds_everything(at_head: str) -> None:
    """The rows are NOT deleted — they cannot be, and the mechanism does not pretend otherwise.
    Quarantine is a read surface, not a removal."""
    assert len(_skus(at_head, "synapse.actions")) == 5


def test_deregistering_a_tenant_makes_its_rows_reappear(at_head: str) -> None:
    """MUTATION PROOF, run against the live objects rather than the source. Emptying the registry
    must restore every row to the view — which proves the exclusion is driven by the registry and
    not by something incidental about those rows.

    It also proves the registry is CORRECTABLE, which is the property that makes a wrong seed a
    one-statement fix rather than a permanent mistake.
    """
    with psycopg.connect(at_head, autocommit=True) as conn:
        conn.execute("DELETE FROM synapse.quarantined_tenants")

    restored = _skus(at_head, "synapse.actions_analytical")
    assert len(restored) == 5, f"emptying the registry did not restore the rows: {sorted(restored)}"


def test_registering_the_real_tenant_hides_it_too(at_head: str) -> None:
    """The other direction: the exclusion follows the registry for ANY tenant, so the view is a
    general mechanism rather than a hard-coded predicate wearing a registry's clothes."""
    with psycopg.connect(at_head, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO synapse.quarantined_tenants "
            "(tenant_id, reason, note, registered_at, registered_by) "
            "VALUES (CAST(%s AS uuid), 'test_fixture', %s, now(), 'test')",
            (_REAL, "x" * 60),
        )
    assert _skus(at_head, "synapse.actions_analytical") == set()


def test_the_reason_vocabulary_is_closed(at_head: str) -> None:
    """A free-text reason would make the registry uncountable, which is the failure the closed
    set on action_events exists to prevent."""
    with psycopg.connect(at_head) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO synapse.quarantined_tenants "
            "(tenant_id, reason, note, registered_at, registered_by) "
            "VALUES (gen_random_uuid(), 'because', %s, now(), 'test')",
            ("x" * 60,),
        )


def test_an_entry_without_real_provenance_is_refused(at_head: str) -> None:
    """The note is the reason the registry was chosen over a predicate. A blank one passes NOT
    NULL and defeats the whole design, so it is length-checked."""
    with psycopg.connect(at_head) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO synapse.quarantined_tenants "
            "(tenant_id, reason, note, registered_at, registered_by) "
            "VALUES (gen_random_uuid(), 'test_fixture', '   ', now(), 'test')"
        )


def test_only_the_reader_may_read_and_nobody_may_write(at_head: str) -> None:
    """THE 0006 LESSON, PINNED. 0001's ALTER DEFAULT PRIVILEGES granted synapse_writer INSERT on
    every future table in this schema and silently handed it action_events. Asserting the
    resulting grant set is cheaper than reasoning about whether views are exempt."""
    with psycopg.connect(at_head) as conn:
        grants: dict[str, str] = dict(
            conn.execute(
                "SELECT grantee, string_agg(DISTINCT privilege_type, ',' ORDER BY privilege_type) "
                "FROM information_schema.table_privileges "
                "WHERE table_schema = 'synapse' AND table_name IN "
                "('quarantined_tenants', 'actions_analytical') AND grantee LIKE 'synapse%' "
                "GROUP BY grantee"
            ).fetchall()
        )
    assert grants == {"synapse_reader": "SELECT"}, grants


def test_the_view_is_security_invoker(at_head: str) -> None:
    """LOAD-BEARING. synapse.actions is FORCE RLS; a view executes with its OWNER's rights by
    default, so an ordinary view over it is a cross-tenant read hole — the opposite of what this
    object is for."""
    with psycopg.connect(at_head) as conn:
        (options,) = conn.execute(
            "SELECT reloptions FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'synapse' AND c.relname = 'actions_analytical'"
        ).fetchone()  # type: ignore[misc]
    assert options is not None and "security_invoker=true" in options, options
