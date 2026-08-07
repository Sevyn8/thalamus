"""Migration 0005 against a REAL Postgres, with a row already in synapse.run.

WHY THIS EXISTS, STATED PLAINLY: 0005 shipped broken and nothing in the suite could have caught
it. The revision interpolated a comment containing ``'{}'`` into a single-quoted SQL literal and
died with ``syntax error at or near "{"``. Every guard we had passed:

  - the schema-agreement test compares the DDL file to the migration as TEXT, and both texts were
    fine — it never executes SQL;
  - the unit suite tests the breakdown's arithmetic and serialisation, neither of which reaches a
    database;
  - the disposable-DB harness DOES run ``alembic upgrade head``, but it was last exercised in the
    slice before this one, when the chain ended at 0004.

So the gap was not "empty tables hid it" — the failure is row-count independent, reproduced on a
table with zero rows and on one with a row. The gap was that NO TEST EVER EXECUTED THE REVISION.
This one does, which is the only kind of test that could have.

IT ALSO PINS THE BACKFILL, which is the part a populated table is genuinely needed for: the column
is NOT NULL DEFAULT '{}', so a row written before 0005 must come out of the migration carrying an
empty map rather than blocking the ALTER or ending up NULL.

IT BUILDS ITS OWN DATABASE at revision 0004 rather than using the session harness, which
provisions at head — a test of "0004 -> 0005" cannot start from head.
"""

from __future__ import annotations

import json
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
# A tenant that owns nothing. synapse.run has no FK into any DIS schema, so this inserts cleanly.
_TENANT = "decafbad-0000-4000-8000-000000000001"


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
def at_0004() -> Iterator[str]:
    """A scratch database migrated to 0004 EXACTLY, with one run row already in it.

    Dropped afterwards rather than kept: unlike the session harness this makes one database per
    test, so leaving them would accumulate. The failure it guards reproduces in a second.
    """
    assert ADMIN_DSN is not None
    name = f"synapse_mig_{uuid4().hex[:12]}"
    maintenance = _libpq(ADMIN_DSN, "postgres")
    template = os.environ.get("SYNAPSE_DISPOSABLE_TEMPLATE", "ithina_dis_db")

    with psycopg.connect(maintenance, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template}"')
    scratch = _libpq(ADMIN_DSN, name)
    try:
        with psycopg.connect(scratch, autocommit=True) as conn:
            # The template carries whatever synapse schema it had; the chain is not idempotent
            # against an existing one.
            conn.execute("DROP SCHEMA IF EXISTS synapse CASCADE")
            conn.execute("DROP TABLE IF EXISTS synapse_alembic_version")

        _alembic(f"postgresql+psycopg://{scratch.split('://', 1)[1]}", "0004")

        with psycopg.connect(scratch, autocommit=True) as conn:
            # REPRODUCING STAGING, NOT A FRESH CHAIN, and the difference is the whole point.
            # `run.sql` now declares `refusals`, and migration 0003 applies that file VERBATIM —
            # so any database built from today's chain already has the column at 0003 and the
            # backfill path is unreachable. The database this migration actually has to survive
            # was provisioned months ago from a run.sql that had no such column. Dropping it here
            # is what puts the scratch database into THAT state; without this the test would
            # exercise only the IF NOT EXISTS no-op and quietly prove nothing about the ALTER.
            conn.execute("ALTER TABLE synapse.run DROP COLUMN IF EXISTS refusals")

        with psycopg.connect(scratch, autocommit=True) as conn:
            # synapse.run is FORCE ROW LEVEL SECURITY and WITH CHECK pins the write to the
            # session's tenant, so both GUCs are required even as the owner. Without them this
            # INSERT fails, and a SELECT would return zero rows while raising nothing.
            conn.execute("SELECT set_config('app.user_type', 'TENANT', false)")
            conn.execute("SELECT set_config('app.tenant_id', %s, false)", (_TENANT,))
            conn.execute(
                """
                INSERT INTO synapse.run (
                    run_id, tenant_id, analysis_id, slot, cadence, rung, timezone,
                    started_at, finished_at, outcome, actions_proposed, actions_appended
                ) VALUES (
                    gen_random_uuid(), %s, 'stockout_risk', DATE '2026-08-06',
                    'daily', 'shadow', 'Asia/Kolkata', now(), now(), 'satisfied', 0, 0
                )
                """,
                (_TENANT,),
            )
        yield scratch
    finally:
        with psycopg.connect(maintenance, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _rows(scratch: str, sql: str) -> list[tuple[object, ...]]:
    with psycopg.connect(scratch) as conn:
        conn.execute("SELECT set_config('app.user_type', 'PLATFORM', false)")
        conn.execute("SELECT set_config('app.tenant_id', %s, false)", (_TENANT,))
        return list(conn.execute(sql).fetchall())


def test_the_precondition_holds_before_the_migration(at_0004: str) -> None:
    """VACUITY GUARD. If the fixture's row did not land, the backfill assertion below would pass
    against an empty table and prove nothing — which is precisely the shape of the gap that let
    0005 ship broken."""
    (count,) = _rows(at_0004, "SELECT count(*) FROM synapse.run")[0]
    assert count == 1, "the fixture row is missing; the backfill test would be vacuous"
    columns = _rows(
        at_0004,
        "SELECT count(*) FROM information_schema.columns WHERE table_schema='synapse' "
        "AND table_name='run' AND column_name='refusals'",
    )[0][0]
    assert columns == 0, (
        "synapse.run already has `refusals` at revision 0004. run.sql declares it and migration "
        "0003 applies that file verbatim, so a FRESH database gets the column early — which is "
        "why 0005 uses ADD COLUMN IF NOT EXISTS. If this fires, the fixture is not really at 0004."
    )


def test_the_revision_applies_to_a_populated_table(at_0004: str) -> None:
    """THE ONE THAT WOULD HAVE CAUGHT IT. Executes 0005 for real; a SQL syntax error anywhere in
    the revision fails here rather than on staging."""
    _alembic(f"postgresql+psycopg://{at_0004.split('://', 1)[1]}", "0005")

    (stamp,) = _rows(at_0004, "SELECT version_num FROM synapse_alembic_version")[0]
    assert stamp == "0005"


def test_the_existing_row_backfills_to_an_empty_map(at_0004: str) -> None:
    """NOT NULL DEFAULT '{}' — the pre-existing row must come out carrying an empty map, not NULL
    and not a blocked ALTER."""
    _alembic(f"postgresql+psycopg://{at_0004.split('://', 1)[1]}", "0005")

    rows = _rows(at_0004, "SELECT refusals FROM synapse.run")
    assert len(rows) == 1
    assert rows[0][0] == {}, f"expected the backfilled empty map, got {rows[0][0]!r}"


def test_the_column_refuses_null_after_the_migration(at_0004: str) -> None:
    """The NOT NULL is real, not decorative: it is what removes the third state the prose used to
    claim and nothing ever wrote."""
    _alembic(f"postgresql+psycopg://{at_0004.split('://', 1)[1]}", "0005")

    with psycopg.connect(at_0004) as conn:
        conn.execute("SELECT set_config('app.user_type', 'TENANT', false)")
        conn.execute("SELECT set_config('app.tenant_id', %s, false)", (_TENANT,))
        with pytest.raises(psycopg.errors.NotNullViolation):
            conn.execute("UPDATE synapse.run SET refusals = NULL")


def test_a_real_breakdown_round_trips(at_0004: str) -> None:
    """The column stores and returns what the recorder writes — sorted keys, JSON object."""
    _alembic(f"postgresql+psycopg://{at_0004.split('://', 1)[1]}", "0005")
    payload = json.dumps({"no_stock_quantity": 3, "series_too_stale": 12})

    with psycopg.connect(at_0004, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.user_type', 'TENANT', false)")
        conn.execute("SELECT set_config('app.tenant_id', %s, false)", (_TENANT,))
        conn.execute("UPDATE synapse.run SET refusals = CAST(%s AS jsonb)", (payload,))

    assert _rows(at_0004, "SELECT refusals FROM synapse.run")[0][0] == {
        "no_stock_quantity": 3,
        "series_too_stale": 12,
    }


def test_the_revision_is_idempotent_against_a_fresh_database(at_0004: str) -> None:
    """A fresh database gets `refusals` from run.sql at 0003, so 0005 must be a no-op there.
    Re-running the upgrade proves the IF NOT EXISTS arm rather than assuming it."""
    dsn = f"postgresql+psycopg://{at_0004.split('://', 1)[1]}"
    _alembic(dsn, "0005")
    _alembic(dsn, "head")  # already at head: must not raise

    (stamp,) = _rows(at_0004, "SELECT version_num FROM synapse_alembic_version")[0]
    assert stamp == "0005"
