"""Migration 0006 against a REAL Postgres. The 0005 lesson applied before shipping, not after.

0005 shipped broken — a SQL syntax error in its own COMMENT — because nothing executed it. The
schema-agreement test compares artifacts as TEXT and the unit suite never reaches a database. So
every migration since runs here, against a database with rows in it, before it goes near staging.

IT HAS ALREADY EARNED ITS PLACE. Running 0006 for the first time showed
``INSERT:synapse_writer`` on synapse.action_events: migration 0001 sets ALTER DEFAULT PRIVILEGES
granting the writer INSERT on every FUTURE table in the schema, so the operator decision log
arrived writable by the orchestrator's identity — defeating the reason this slice took a third
role at all. Reading the migration would not have shown that; the grant comes from somewhere
else entirely. ``test_only_the_lifecycle_role_may_write`` is that finding, pinned.

WHAT ELSE ONLY A DATABASE CAN ANSWER: that the append-only trigger binds the owner, and that each
CHECK refuses its illegal combination. Both are asserted below against the real constraints
rather than against the Python mirrors of them in lifecycle.py.
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
_TENANT = "decafbad-0000-4000-8000-000000000001"
_TARGET = '{"tenant_id": "decafbad-0000-4000-8000-000000000001", "store_id": "s", "sku_id": "SKU-1"}'


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


@pytest.fixture
def at_head() -> Iterator[str]:
    """A scratch database migrated through 0006, with one lifecycle event already in it.

    POPULATED BEFORE THE ASSERTIONS, deliberately: an append-only check against an empty table
    cannot tell "refused the update" from "matched no row", which is the 0-rows-prove-nothing
    failure this project keeps paying for.
    """
    assert ADMIN_DSN is not None
    name = f"synapse_mig6_{uuid4().hex[:12]}"
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
            # FORCE RLS with WITH CHECK on app.tenant_id: both GUCs are required even as the
            # owner, and without them this INSERT is refused rather than silently dropped.
            _as_tenant(conn)
            conn.execute(
                """
                INSERT INTO synapse.action_events (
                    lifecycle_event_id, action_event_id, tenant_id, declaration_id, target,
                    verb, reason, snoozed_until, actor_subject, recorded_at
                ) VALUES (
                    gen_random_uuid(), gen_random_uuid(), %s, 'dead_stock', CAST(%s AS jsonb),
                    'acknowledge', NULL, NULL, 'auth0|seed', now()
                )
                """,
                (_TENANT, _TARGET),
            )
        yield scratch
    finally:
        with psycopg.connect(maintenance, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _as_tenant(conn: psycopg.Connection[object]) -> None:
    conn.execute("SELECT set_config('app.user_type', 'TENANT', false)")
    conn.execute("SELECT set_config('app.tenant_id', %s, false)", (_TENANT,))


def _insert(conn: psycopg.Connection[object], **cols: object) -> None:
    values = {
        "verb": "acknowledge",
        "reason": None,
        "snoozed_until": None,
        **cols,
    }
    conn.execute(
        """
        INSERT INTO synapse.action_events (
            lifecycle_event_id, action_event_id, tenant_id, declaration_id, target,
            verb, reason, snoozed_until, actor_subject, recorded_at
        ) VALUES (
            gen_random_uuid(), gen_random_uuid(), %s, 'dead_stock', CAST(%s AS jsonb),
            %s, %s, %s, 'auth0|t', now()
        )
        """,
        (_TENANT, _TARGET, values["verb"], values["reason"], values["snoozed_until"]),
    )


def test_the_chain_reaches_0006_and_the_seed_row_landed(at_head: str) -> None:
    """VACUITY GUARD. Every assertion below is about a table with a row in it."""
    with psycopg.connect(at_head) as conn:
        _as_tenant(conn)
        (stamp,) = conn.execute("SELECT version_num FROM synapse_alembic_version").fetchone()  # type: ignore[misc]
        (count,) = conn.execute("SELECT count(*) FROM synapse.action_events").fetchone()  # type: ignore[misc]
    assert stamp == "0006"
    assert count == 1, "the seed event is missing; the append-only checks would be vacuous"


def test_the_table_refuses_update_and_delete_even_as_the_owner(at_head: str) -> None:
    """THE TRIGGER, not the grant. These run as the schema owner, who holds every privilege —
    so a grant-only mechanism would let this through. Changing a decision is a NEW event."""
    with psycopg.connect(at_head) as conn:
        _as_tenant(conn)
        with pytest.raises(psycopg.errors.RestrictViolation):
            conn.execute("UPDATE synapse.action_events SET verb = 'dismiss'")
    with psycopg.connect(at_head) as conn:
        _as_tenant(conn)
        with pytest.raises(psycopg.errors.RestrictViolation):
            conn.execute("DELETE FROM synapse.action_events")


@pytest.mark.parametrize(
    ("label", "cols"),
    [
        ("unknown verb", {"verb": "archive"}),
        ("dismiss with no reason", {"verb": "dismiss"}),
        ("dismiss with an unknown reason", {"verb": "dismiss", "reason": "because"}),
        ("acknowledge carrying a reason", {"verb": "acknowledge", "reason": "seasonal"}),
        ("snooze with no expiry", {"verb": "snooze"}),
        ("acknowledge carrying an expiry", {"verb": "acknowledge", "snoozed_until": "2026-09-01"}),
    ],
)
def test_the_check_constraints_refuse_every_illegal_combination(
    at_head: str, label: str, cols: dict[str, object]
) -> None:
    """THE DATABASE'S OWN VOCABULARY, not lifecycle.py's mirror of it. The Python enums give a
    good error message; these constraints are what make the vocabulary true of the data even if
    something writes around the service."""
    with psycopg.connect(at_head) as conn:
        _as_tenant(conn)
        with pytest.raises(psycopg.errors.CheckViolation):
            _insert(conn, **cols)


@pytest.mark.parametrize(
    ("label", "cols"),
    [
        ("acknowledge", {"verb": "acknowledge"}),
        ("dismiss with a label", {"verb": "dismiss", "reason": "wrong_data"}),
        ("snooze with an expiry", {"verb": "snooze", "snoozed_until": "2026-09-01"}),
    ],
)
def test_the_legal_combinations_are_accepted(at_head: str, label: str, cols: dict[str, object]) -> None:
    """THE BASELINE. Without it every refusal above would pass against a table that rejected
    everything."""
    with psycopg.connect(at_head, autocommit=True) as conn:
        _as_tenant(conn)
        _insert(conn, **cols)


def test_only_the_lifecycle_role_may_write(at_head: str) -> None:
    """THE FINDING THIS FILE PAID FOR ITSELF WITH.

    0001's ALTER DEFAULT PRIVILEGES grants synapse_writer INSERT on every FUTURE table in the
    schema, so action_events arrived writable by the ORCHESTRATOR's identity — which would make
    every row ambiguous about whether a human or the 04:00 sweep produced it, and defeat the
    reason for taking a third role. Reading 0006 could not show this; the grant comes from a
    different migration.
    """
    with psycopg.connect(at_head) as conn:
        grants: dict[str, str] = dict(
            conn.execute(
                "SELECT grantee, string_agg(privilege_type, ',' ORDER BY privilege_type) "
                "FROM information_schema.table_privileges "
                "WHERE table_schema = 'synapse' AND table_name = 'action_events' "
                "AND grantee LIKE 'synapse%' GROUP BY grantee"
            ).fetchall()
        )
    assert grants == {"synapse_lifecycle": "INSERT", "synapse_reader": "SELECT"}, grants


def test_the_table_is_force_rls_with_a_policy(at_head: str) -> None:
    """Enabled is not enough: FORCE is what makes the policy apply to the owner too, and without
    it a tenant could be written an event by a session acting for another."""
    with psycopg.connect(at_head) as conn:
        (enabled, forced) = conn.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'synapse' AND c.relname = 'action_events'"
        ).fetchone()  # type: ignore[misc]
        (policies,) = conn.execute(
            "SELECT count(*) FROM pg_policies WHERE schemaname = 'synapse' AND tablename = 'action_events'"
        ).fetchone()  # type: ignore[misc]
    assert enabled and forced
    assert policies == 1


def test_a_cross_tenant_write_is_refused(at_head: str) -> None:
    """WITH CHECK compares app.tenant_id — what forces the service's write onto a TENANT-scoped
    session and makes a PLATFORM one incapable of writing at all.

    `SET ROLE synapse_lifecycle` FIRST, AND THAT IS THE WHOLE TEST. The first version ran as the
    connection's own role and DID NOT RAISE: on this devbox that role is a SUPERUSER, and a
    superuser bypasses RLS entirely no matter what FORCE says. It would have shipped as a green
    assertion about a policy it never reached — this project's standing "a local superuser repro
    proves nothing under FORCE RLS" trap, walked into while writing the test for it.

    SET ROLE needs no password from a superuser, so the check runs as the NOBYPASSRLS role that
    actually serves this write in production.
    """
    with psycopg.connect(at_head) as conn:
        conn.execute("SET ROLE synapse_lifecycle")
        bypasses = conn.execute(
            "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        assert bypasses is not None and bypasses[0] is False, (
            "the session role bypasses RLS, so this test cannot observe the policy at all"
        )
        conn.execute("SELECT set_config('app.user_type', 'TENANT', false)")
        conn.execute("SELECT set_config('app.tenant_id', 'decafbad-0000-4000-8000-0000000000ff', false)")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            _insert(conn)
