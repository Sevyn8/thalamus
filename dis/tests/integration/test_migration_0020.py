"""Migration 0020 (retire the ROOS narrative from deployed comments).

Proves, against the resident DIS database (5433, read-only reference) and an ephemeral
scratch DB:

  * **Target-safety guard** (pure, always-run, never skips): refuses Customer Master
    and any non-DIS database; passes the DIS database.
  * **Migration constant == schema file**, for all three comments. This is the drift a
    comment-only migration actually risks: 0001 applies the ``schemas/postgres`` DDL
    verbatim on the fresh path while 0020 sets the text on the delta path, so if the two
    disagree the database looks internally consistent on either path and they disagree
    with each other. Asserted per comment rather than in aggregate, so a failure names
    which one drifted.
  * **The retired name is gone and the surviving claims are not**, on the resident DB.
    "No ROOS" alone would also pass if the comment were emptied or the column dropped, so
    each assertion pairs the absence with the substance that must remain.
  * **Fresh == migrated** on a scratch DB: the full chain lands the identical text the
    resident migrated reference carries.

Mirrors ``test_migration_0015.py`` (the comment-reconciliation precedent) in shape and in
the fixtures it uses.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Engine, text

from dis_testing.migration_harness import ScratchDB, alembic_head

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_PATH = _REPO_ROOT / "alembic" / "versions" / "0020_retire_roos_narrative_metadata.py"
_CANONICAL_FILE = (
    _REPO_ROOT / "schemas" / "postgres" / "canonical" / "store_sku_current_position.sql"
)
_STAGING_FILE = (
    _REPO_ROOT / "schemas" / "postgres" / "staging" / "store_sku_current_position.sql"
)

_TABLE = "store_sku_current_position"
_COL = "yesterday_retail_price"
_RETIRED = "ROOS"


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0020", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _literal(path: Path, pattern: str) -> str:
    """Extract a single-quoted COMMENT literal from a DDL file and un-double its quotes."""
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.DOTALL)
    assert match is not None, f"COMMENT not found in {path.name} for pattern {pattern!r}"
    return match.group(1).replace("''", "'")


def _schema_file_table_comment() -> str:
    return _literal(
        _CANONICAL_FILE,
        r"COMMENT ON TABLE canonical\.store_sku_current_position IS\s*'(.*?)';",
    )


def _schema_file_column_comment(path: Path, schema: str) -> str:
    return _literal(
        path,
        rf"COMMENT ON COLUMN {schema}\.store_sku_current_position\.yesterday_retail_price"
        r" IS\s*'(.*?)';",
    )


def _table_comment(engine: Engine, schema: str) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT obj_description(c.oid, 'pg_class') FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :s AND c.relname = :t"
            ),
            {"s": schema, "t": _TABLE},
        ).scalar()


def _column_comment(engine: Engine, schema: str) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT col_description(c.oid, a.attnum) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_attribute a ON a.attrelid = c.oid "
                "WHERE n.nspname = :s AND c.relname = :t AND a.attname = :col"
            ),
            {"s": schema, "t": _TABLE, "col": _COL},
        ).scalar()


# --- Target-safety guard: pure, always-run, never skips (no DB) ---------------


def test_guard_refuses_customer_master() -> None:
    mod = _load_migration_module()
    with pytest.raises(RuntimeError, match="Customer Master"):
        mod.check_migration_target("ithina_platform_db", expected_db="ithina_dis_db")


def test_guard_refuses_unexpected_database() -> None:
    mod = _load_migration_module()
    with pytest.raises(RuntimeError, match="expected"):
        mod.check_migration_target("some_other_db", expected_db="ithina_dis_db")


def test_guard_passes_the_dis_database_positively() -> None:
    mod = _load_migration_module()
    mod.check_migration_target("ithina_dis_db", expected_db="ithina_dis_db")


# --- Migration constants pinned to the schema files (drift guard, no DB) ------


def test_migration_table_comment_matches_the_schema_file() -> None:
    mod = _load_migration_module()
    assert mod._NEW_TABLE_COMMENT == _schema_file_table_comment()


def test_migration_column_comment_matches_both_schema_files() -> None:
    """canonical and staging carry byte-identical text, driven by one migration constant."""
    mod = _load_migration_module()
    canonical = _schema_file_column_comment(_CANONICAL_FILE, "canonical")
    staging = _schema_file_column_comment(_STAGING_FILE, "staging")
    assert canonical == staging, "canonical and staging column comments have drifted apart"
    assert mod._NEW_COLUMN_COMMENT == canonical


def test_the_old_constants_are_what_the_migration_replaces() -> None:
    """The downgrade text must be the string that was actually deployed, not a paraphrase.

    A downgrade that writes an invented "previous" comment is worse than no downgrade: it
    reports success while leaving the database in a state it was never in.
    """
    mod = _load_migration_module()
    assert _RETIRED in mod._OLD_TABLE_COMMENT
    assert _RETIRED in mod._OLD_COLUMN_COMMENT
    assert _RETIRED not in mod._NEW_TABLE_COMMENT
    assert _RETIRED not in mod._NEW_COLUMN_COMMENT


# --- Resident database at head (read-only) ------------------------------------


@pytest.mark.parametrize(
    ("schema", "path"),
    [("canonical", _CANONICAL_FILE), ("staging", _STAGING_FILE)],
)
def test_resident_column_comment_matches_schema_file(
    admin_engine: Engine, schema: str, path: Path
) -> None:
    live = _column_comment(admin_engine, schema)
    assert live is not None, f"{schema}.{_TABLE}.{_COL} has no comment at all"
    assert live == _schema_file_column_comment(path, schema)
    # Absence plus substance: an emptied comment would satisfy the first half alone.
    assert _RETIRED not in live
    assert "Previous-day retail price" in live
    assert "TBD" in live


def test_resident_table_comment_matches_schema_file(admin_engine: Engine) -> None:
    live = _table_comment(admin_engine, "canonical")
    assert live is not None
    assert live == _schema_file_table_comment()
    assert _RETIRED not in live
    assert "dis-ui-server" in live
    assert "Tenant-isolated via RLS" in live


def test_no_dis_comment_anywhere_still_names_the_retired_module(admin_engine: Engine) -> None:
    """Sweep the whole catalogue rather than the three objects this migration knows about.

    The three were found by exactly this query before the migration was written; running it
    again is what proves the list was complete rather than the list this author happened to
    look for.
    """
    with admin_engine.connect() as conn:
        hits = conn.execute(
            text(
                """
                SELECT n.nspname || '.' || c.relname AS obj
                  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE obj_description(c.oid, 'pg_class') ILIKE :pat
                UNION ALL
                SELECT n.nspname || '.' || c.relname || '.' || a.attname
                  FROM pg_class c
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                  JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0
                 WHERE col_description(c.oid, a.attnum) ILIKE :pat
                """
            ),
            {"pat": f"%{_RETIRED}%"},
        ).scalars().all()
    assert hits == [], f"database comments still name the retired module: {hits}"


# --- Fresh == migrated --------------------------------------------------------


def test_fresh_bootstrap_converges_with_delta_path(
    scratch_db: ScratchDB, admin_engine: Engine
) -> None:
    """The chain upgrades clean to head and lands identical text on a fresh scratch DB."""
    with scratch_db.engine.connect() as conn:
        head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert head == alembic_head()

    for schema, path in (("canonical", _CANONICAL_FILE), ("staging", _STAGING_FILE)):
        fresh = _column_comment(scratch_db.engine, schema)
        delta = _column_comment(admin_engine, schema)
        assert fresh == _schema_file_column_comment(path, schema)
        assert fresh == delta, (
            f"fresh bootstrap produced a different {schema}.{_COL} comment than the "
            "migrated reference — the DDL file and migration 0020 disagree"
        )

    fresh_table = _table_comment(scratch_db.engine, "canonical")
    assert fresh_table == _schema_file_table_comment()
    assert fresh_table == _table_comment(admin_engine, "canonical")
