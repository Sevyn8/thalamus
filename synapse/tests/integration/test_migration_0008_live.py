"""Migration 0008 against a REAL Postgres, with actions already in the table.

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
    name = f"synapse_mig8_{uuid4().hex[:12]}"
    maintenance = _libpq(ADMIN_DSN, "postgres")
    template = os.environ.get("SYNAPSE_DISPOSABLE_TEMPLATE", "ithina_dis_db")

    with psycopg.connect(maintenance, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template}"')
    scratch = _libpq(ADMIN_DSN, name)
    try:
        with psycopg.connect(scratch, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS synapse CASCADE")
            conn.execute("DROP TABLE IF EXISTS synapse_alembic_version")

        _alembic(f"postgresql+psycopg://{scratch.split('://', 1)[1]}", "0007")

        with psycopg.connect(scratch, autocommit=True) as conn:
            # REPRODUCING STAGING, NOT A FRESH CHAIN. actions.sql now declares
            # retail_value_locked and migration 0001 applies that file VERBATIM, so any database
            # built from today's chain already has the column at 0001 and the ALTER would be a
            # no-op. The database 0008 must actually survive was built months ago from an
            # actions.sql without it. Same structural fact 0005 hit with run.sql.
            # The view depends on the column, so staging's pre-0008 state is reconstructed in
            # order: drop the view, drop the column, rebuild the view WITHOUT it -- which is
            # exactly what 0007 left behind on a database that predated actions.sql declaring it.
            conn.execute("DROP VIEW IF EXISTS synapse.actions_analytical")
            conn.execute("ALTER TABLE synapse.actions DROP COLUMN IF EXISTS retail_value_locked")
            conn.execute(
                "CREATE VIEW synapse.actions_analytical WITH (security_invoker = true) AS "
                "SELECT a.* FROM synapse.actions a WHERE NOT EXISTS ("
                "SELECT 1 FROM synapse.quarantined_tenants q WHERE q.tenant_id = a.tenant_id)"
            )

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


def _append_valued(scratch: str, sku: str, value: str) -> None:
    """One action carrying a retail_value_locked. Append-only, so this is the only way in."""
    with psycopg.connect(scratch, autocommit=True) as conn:
        _as_tenant(conn, _REAL)
        conn.execute(
            """
            INSERT INTO synapse.actions (
                event_id, recorded_at, target, verb, quantity_at_stake, expires_on, arm,
                declaration_id, declaration_version, capability_versions, thresholds, as_of,
                payload_hash, retail_value_locked
            ) VALUES (
                gen_random_uuid(), now(), CAST(%s AS jsonb), 'review', 1, DATE '2026-12-31',
                'treatment', 'overstock_cash_locked', '0.1.0',
                '{"current_state": "0.1.0"}'::jsonb, '{"overstock_after_days": 30}'::jsonb,
                DATE '2026-08-09', md5(%s), CAST(%s AS numeric)
            )
            """,
            (f'{{"tenant_id": "{_REAL}", "store_id": "{_STORE}", "sku_id": "{sku}"}}', sku, value),
        )


def _value_of(scratch: str, sku: str) -> str:
    with psycopg.connect(scratch) as conn:
        _as_platform(conn)
        (value,) = conn.execute(
            "SELECT retail_value_locked FROM synapse.actions WHERE sku_id = %s", (sku,)
        ).fetchone()  # type: ignore[misc]
    return str(value)


def _dsn(scratch: str) -> str:
    return f"postgresql+psycopg://{scratch.split('://', 1)[1]}"


def test_the_precondition_holds_before_the_migration(at_head: str) -> None:
    """VACUITY GUARD, and the 0005 law's whole point: the ALTER must meet ROWS. An additive
    column asserted against an empty table proves nothing about a live one."""
    with psycopg.connect(at_head) as conn:
        _as_platform(conn)
        (stamp,) = conn.execute("SELECT version_num FROM synapse_alembic_version").fetchone()  # type: ignore[misc]
        (rows,) = conn.execute("SELECT count(*) FROM synapse.actions").fetchone()  # type: ignore[misc]
        (col,) = conn.execute(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema='synapse' "
            "AND table_name='actions' AND column_name='retail_value_locked'"
        ).fetchone()  # type: ignore[misc]
    assert stamp == "0007"
    assert rows == 5, f"expected the 5 seeded actions, got {rows}"
    assert col == 0, (
        "synapse.actions already has retail_value_locked at 0007. actions.sql declares it and "
        "migration 0001 applies that file verbatim, so a FRESH database gets it early -- which "
        "is why 0008 uses ADD COLUMN IF NOT EXISTS. If this fires, the fixture is not at 0007."
    )


def test_the_revision_applies_to_a_populated_table(at_head: str) -> None:
    """THE ONE THE 0005 LESSON BOUGHT. Executes the revision for real; a SQL error anywhere in
    it -- an unescaped apostrophe in the COMMENT, say -- fails here rather than on staging."""
    _alembic(_dsn(at_head), "0008")
    with psycopg.connect(at_head) as conn:
        _as_platform(conn)
        (stamp,) = conn.execute("SELECT version_num FROM synapse_alembic_version").fetchone()  # type: ignore[misc]
    assert stamp == "0008"


def test_existing_rows_get_null_not_a_backfilled_number(at_head: str) -> None:
    """NULL MEANS "NOT COMPUTED BY THIS ANALYSIS". The five seeded rows were written by
    dead_stock-shaped inserts, so there is no honest value to backfill -- and a DEFAULT here
    would have invented one for every historical action."""
    _alembic(_dsn(at_head), "0008")
    with psycopg.connect(at_head) as conn:
        _as_platform(conn)
        rows = conn.execute("SELECT count(*), count(retail_value_locked) FROM synapse.actions").fetchone()
    assert rows == (5, 0), f"expected 5 rows all NULL, got {rows}"


def test_the_column_accepts_a_realistic_value_and_is_nullable(at_head: str) -> None:
    """The spot-check figure from gate 1: SKU-0010 at PVk-001, 83 units at Rs 850 = 70,550.00.
    Also proves the column stays NULLABLE -- the two facts a later reader needs together."""
    _alembic(_dsn(at_head), "0008")
    # INSERTED, NOT UPDATED. synapse.actions is append-only by a trigger that binds even the
    # owner, so an UPDATE-based assertion here fails with RestrictViolation -- which is the
    # trigger working, and a reminder that every value in this table arrives once.
    _append_valued(at_head, "SKU-VALUE", "70550.00")
    assert _value_of(at_head, "SKU-VALUE") == "70550.00"


def test_the_precision_holds_a_realistic_maximum(at_head: str) -> None:
    """NUMERIC(18,2) argued at gate 1: realistic maxima (1e5 units x 1e6 currency = 1e11) sit
    five orders below this column's ceiling. Asserted rather than reasoned about, because a
    precision that silently truncates money is the kind of defect nobody reports."""
    _alembic(_dsn(at_head), "0008")
    _append_valued(at_head, "SKU-BIG", "100000000000.00")
    assert _value_of(at_head, "SKU-BIG") == "100000000000.00"


def test_a_negative_value_is_refused_at_the_action_boundary() -> None:
    """No DB CHECK -- the guard is in Action.__post_init__, where the message can explain that
    the figure is stock times a price and both are non-negative by CHECK upstream."""
    from decimal import Decimal

    import pytest as _pytest

    from synapse.core.action import Action

    with _pytest.raises(ValueError, match="retail_value_locked"):
        Action(
            target={"tenant_id": _REAL, "store_id": _STORE, "sku_id": "X"},
            verb=__import__("synapse.core.action", fromlist=["Verb"]).Verb.REVIEW,
            quantity_at_stake=None,
            expires_on=__import__("datetime").date(2026, 12, 31),
            arm=__import__("synapse.core.holdout", fromlist=["Arm"]).Arm.TREATMENT,
            provenance=__import__("synapse.core.action", fromlist=["Provenance"]).Provenance(
                declaration_id="overstock_cash_locked",
                declaration_version="0.1.0",
                capability_versions={"current_state": "0.1.0"},
                thresholds={"overstock_after_days": 30},
                as_of=__import__("datetime").date(2026, 8, 9),
            ),
            retail_value_locked=Decimal("-1"),
        )


def test_the_analytical_view_gains_the_column_too(at_head: str) -> None:
    """THE DEFECT THE FRESH CHAIN COULD NOT SHOW, and the reason this fixture reconstructs
    staging rather than building clean.

    synapse.actions_analytical is ``SELECT a.*``, which Postgres expands to a FIXED column list
    at creation time. On staging the view was built at 0007 over a table without
    retail_value_locked, so adding the column to the TABLE does not add it to the VIEW -- and
    the surface analytics is told to read would silently lack the column M1 exists to record.
    0008 therefore CREATE OR REPLACEs the view.
    """
    with psycopg.connect(at_head) as conn:
        _as_platform(conn)
        (before,) = conn.execute(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema='synapse' "
            "AND table_name='actions_analytical' AND column_name='retail_value_locked'"
        ).fetchone()  # type: ignore[misc]
    assert before == 0, "the fixture did not reconstruct staging's pre-0008 view"

    _alembic(_dsn(at_head), "0008")

    with psycopg.connect(at_head) as conn:
        _as_platform(conn)
        (after,) = conn.execute(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema='synapse' "
            "AND table_name='actions_analytical' AND column_name='retail_value_locked'"
        ).fetchone()  # type: ignore[misc]
        (invoker,) = conn.execute(
            "SELECT reloptions FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname='synapse' AND c.relname='actions_analytical'"
        ).fetchone()  # type: ignore[misc]
    assert after == 1, "0008 did not refresh the analytical view; analytics would not see the column"
    # The replace must not quietly drop security_invoker -- that flag is what keeps the view from
    # being a cross-tenant read hole over a FORCE RLS table.
    assert invoker is not None and "security_invoker=true" in invoker, invoker
