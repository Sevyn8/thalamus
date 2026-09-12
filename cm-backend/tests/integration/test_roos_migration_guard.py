"""The ROOS migration's dependency preflight must actually detect dependents.

WHY THIS FILE EXISTS. The first implementation of that preflight joined ``pg_class`` on
``pg_depend.refobjid`` — the OID of the REFERENCED object, which for this check is the enum type
— and filtered on ``relkind IN ('v','m')``. That asks whether some relation happens to share an
OID with a type. It is not a dependency question, it returns nothing however many dependents
exist, and the migration read that nothing as "safe to proceed". A guard whose only evidence is
that it returned an empty list is indistinguishable from a guard that cannot return anything.

So this file builds the dependents for real, in the live catalogue, and asserts the guard names
them. No mocked ``pg_catalog`` rows: the defect being regressed was a misreading of catalogue
semantics, and a fake catalogue would have agreed with the misreading.

FIVE CLASSES ARE EXERCISED, and the last one is the reason the corrected guard needs two scans:

  1. a view exposing a column OF the enum type          (pg_class dependent of the type)
  2. a materialized view exposing such a column         (pg_class dependent of the type)
  3. a function taking the enum as an argument          (pg_proc dependent of the type)
  4. a function returning the enum                      (pg_proc dependent of the type)
  5. a view that only CASTS the column to text          (pg_rewrite dependent of the COLUMN)

Class 5 records no dependency on the type whatsoever, so a scan that looks only at the type
misses it — while Postgres still refuses the ALTER with "cannot alter type of a column used by
a view or rule". It is the case that proves the column scan is load-bearing rather than
belt-and-braces.

The transactional half of the property — that a refused upgrade leaves the database at the
previous revision — needs a database at the previous head, which needs CREATEDB. The CI role is
deliberately NOCREATEDB, so that half is verified out-of-band against a disposable database and
is recorded in the pull request rather than asserted here. What this file proves is the half
that can run on every pull request: given a real dependent, the guard returns it.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from admin_backend.config import get_settings

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "0fdfbc8871a8_remove_roos_module.py"
)


def _load_migration() -> ModuleType:
    """Import the revision file directly — ``migrations/versions`` is not an importable package.

    Loading the real module rather than re-implementing its query is the whole point: a copy of
    the SQL in the test would pass while the migration shipped something different.
    """
    spec = importlib.util.spec_from_file_location("roos_removal_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_revision_file_is_where_this_test_thinks_it_is() -> None:
    """Vacuity guard. Every assertion below is meaningless if the import silently found nothing."""
    assert _MIGRATION.exists(), f"migration not found at {_MIGRATION}"
    migration = _load_migration()
    assert migration.revision == "0fdfbc8871a8"
    assert callable(migration.blocking_dependents)


async def test_a_clean_database_reports_no_blocking_dependents(engine: AsyncEngine) -> None:
    """The baseline. Without it, "the guard found nothing" below proves nothing either.

    The two UNIQUE constraints over these columns DO depend on them and are deliberately not
    reported: ALTER COLUMN TYPE rebuilds constraints and indexes itself, so reporting them would
    make the guard refuse every run.
    """
    migration = _load_migration()
    schema = get_settings().db_schema

    async with engine.connect() as conn:
        await conn.execute(text(f"SET search_path TO {schema}, public"))
        found = await conn.run_sync(
            lambda sync_conn: migration.blocking_dependents(sync_conn)
        )

    assert found == [], f"a clean database reports blocking dependents: {found}"


@pytest.mark.parametrize(
    ("label", "create", "drop", "expected_fragment"),
    [
        (
            "view exposing an enum column",
            "CREATE VIEW {s}.guard_probe_v AS SELECT id, module FROM {s}.permissions",
            "DROP VIEW IF EXISTS {s}.guard_probe_v",
            "guard_probe_v",
        ),
        (
            "materialized view exposing an enum column",
            "CREATE MATERIALIZED VIEW {s}.guard_probe_mv AS "
            "SELECT module, count(*) AS n FROM {s}.permissions GROUP BY module",
            "DROP MATERIALIZED VIEW IF EXISTS {s}.guard_probe_mv",
            "guard_probe_mv",
        ),
        (
            "function taking the enum as an argument",
            "CREATE FUNCTION {s}.guard_probe_arg(m {s}.module_code_enum) RETURNS text "
            "LANGUAGE sql IMMUTABLE AS $$ SELECT m::text $$",
            "DROP FUNCTION IF EXISTS {s}.guard_probe_arg({s}.module_code_enum)",
            "guard_probe_arg",
        ),
        (
            "function returning the enum",
            "CREATE FUNCTION {s}.guard_probe_ret() RETURNS {s}.module_code_enum "
            "LANGUAGE sql IMMUTABLE AS $$ SELECT 'ADMIN'::{s}.module_code_enum $$",
            "DROP FUNCTION IF EXISTS {s}.guard_probe_ret()",
            "guard_probe_ret",
        ),
        (
            # THE ONE THE TYPE SCAN CANNOT SEE. Casting to text means the rule depends on the
            # column and not on the enum type, so only the column scan reports it — and
            # Postgres still refuses ALTER COLUMN TYPE while it exists.
            "view casting the enum column to text",
            "CREATE VIEW {s}.guard_probe_cast AS "
            "SELECT id FROM {s}.permissions WHERE module::text = 'ADMIN'",
            "DROP VIEW IF EXISTS {s}.guard_probe_cast",
            "guard_probe_cast",
        ),
    ],
    ids=["view", "matview", "function-arg", "function-return", "cast-only-view"],
)
async def test_the_guard_reports_each_class_of_dependent(
    engine: AsyncEngine, label: str, create: str, drop: str, expected_fragment: str
) -> None:
    """Create a real dependent, assert the guard names it, drop it, assert the guard clears.

    The drop-and-clear half matters as much as the detection half: a guard that reports a
    dependent unconditionally would pass the first assertion and block every migration forever.
    """
    migration = _load_migration()
    schema = get_settings().db_schema

    async with engine.connect() as conn:
        await conn.execute(text(f"SET search_path TO {schema}, public"))
        await conn.execute(text(drop.format(s=schema)))
        await conn.execute(text(create.format(s=schema)))
        await conn.commit()

    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET search_path TO {schema}, public"))
            found = await conn.run_sync(
                lambda sync_conn: migration.blocking_dependents(sync_conn)
            )
        assert any(expected_fragment in entry for entry in found), (
            f"the guard did not report the {label}. Reported: {found}"
        )
    finally:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET search_path TO {schema}, public"))
            await conn.execute(text(drop.format(s=schema)))
            await conn.commit()

    async with engine.connect() as conn:
        await conn.execute(text(f"SET search_path TO {schema}, public"))
        cleared = await conn.run_sync(
            lambda sync_conn: migration.blocking_dependents(sync_conn)
        )
    assert cleared == [], f"the guard still reports dependents after cleanup: {cleared}"


async def test_a_cast_only_view_is_invisible_to_a_type_only_scan(engine: AsyncEngine) -> None:
    """The asymmetry that forces two scans, asserted rather than left in a comment.

    This is the measurement that justifies the column scan's existence. If a future edit
    simplifies ``blocking_dependents`` back to a single scan over the type, the parametrised
    case above starts failing and this test says why in one line.
    """
    schema = get_settings().db_schema
    # Relations are resolved by (namespace, name) joins rather than by casting a bind parameter
    # to regclass: ``(:name)::regclass`` is not a form psycopg will accept here.
    _REL = """
        SELECT c.oid FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = :schema AND c.relname = :rel
    """
    type_scan = text(
        f"""
        SELECT count(*)
          FROM pg_depend d
          JOIN pg_rewrite r ON r.oid = d.objid AND d.classid = 'pg_rewrite'::regclass
         WHERE d.refclassid = 'pg_type'::regclass
           AND d.refobjid = (SELECT t.oid FROM pg_type t
                              JOIN pg_namespace n ON n.oid = t.typnamespace
                             WHERE t.typname = 'module_code_enum' AND n.nspname = :schema)
           AND r.ev_class = ({_REL})
        """
    )
    column_scan = text(
        f"""
        SELECT count(*)
          FROM pg_depend d
          JOIN pg_rewrite r ON r.oid = d.objid AND d.classid = 'pg_rewrite'::regclass
         WHERE d.refclassid = 'pg_class'::regclass
           AND d.refobjid = (SELECT c.oid FROM pg_class c
                              JOIN pg_namespace n ON n.oid = c.relnamespace
                             WHERE n.nspname = :schema AND c.relname = :table_name)
           AND d.refobjsubid = (SELECT a.attnum FROM pg_attribute a
                                 JOIN pg_class c ON c.oid = a.attrelid
                                 JOIN pg_namespace n ON n.oid = c.relnamespace
                                WHERE n.nspname = :schema AND c.relname = :table_name
                                  AND a.attname = 'module')
           AND r.ev_class = ({_REL})
        """
    )
    params = {
        "schema": schema,
        "rel": "guard_asym_cast",
        "table_name": "permissions",
    }

    async with engine.connect() as conn:
        await conn.execute(text(f"DROP VIEW IF EXISTS {schema}.guard_asym_cast"))
        await conn.execute(
            text(
                f"CREATE VIEW {schema}.guard_asym_cast AS "
                f"SELECT id FROM {schema}.permissions WHERE module::text = 'ADMIN'"
            )
        )
        await conn.commit()

    try:
        async with engine.connect() as conn:
            via_type = (await conn.execute(type_scan, params)).scalar_one()
            via_column = (await conn.execute(column_scan, params)).scalar_one()

        assert via_type == 0, (
            "a cast-only view now registers a dependency on the type; if Postgres changed this, "
            "the two-scan rationale in the migration needs rewriting rather than trusting"
        )
        assert via_column == 1, "the column scan failed to see a cast-only view's rule"
    finally:
        async with engine.connect() as conn:
            await conn.execute(text(f"DROP VIEW IF EXISTS {schema}.guard_asym_cast"))
            await conn.commit()
