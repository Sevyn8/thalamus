"""Migration 0015 (reconcile attribute_staleness_map column comment — Slice 50d).

Proves, against the resident DIS database (5433, read-only reference) and an ephemeral
scratch DB (Slice 51c, D122):

  * **Target-safety guard** (pure, always-run, never skips): refuses Customer Master
    and any non-DIS database; passes the DIS database.
  * **Comment reconciled at head** (the headline effect): the resident
    ``attribute_staleness_map`` column comment equals the Slice 50d text — and,
    load-bearing, equals the text in the schema-file DDL. Because 0015 sets the comment
    on BOTH the fresh-bootstrap and delta paths, the real drift risk a comment-only
    migration must guard is migration-constant vs schema-file divergence; this asserts
    schema-file == migration constant == resident DB.
  * **Fresh == migrated** on a scratch DB: the full chain (0001 applies the edited DDL
    comment, … , 0015 re-applies it) upgrades clean to head and lands the identical
    comment the resident migrated reference carries.

Downgrade-reversibility (restore the pre-slice comment) is deferred until staging (D99),
matching the 0014 precedent; the downgrade leg is authored in the migration.

See: docs/slices/slice-50d-staleness-map-rework.md, the 0005 COMMENT-reconciliation
precedent, the 0014 fresh==migrated scratch-DB precedent.
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
_MIGRATION_PATH = _REPO_ROOT / "alembic" / "versions" / "0015_staleness_map_comment.py"
_SCHEMA_FILE = _REPO_ROOT / "schemas" / "postgres" / "canonical" / "store_sku_current_position.sql"

_SCHEMA = "canonical"
_TABLE = "store_sku_current_position"
_COL = "attribute_staleness_map"


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0015", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schema_file_comment() -> str:
    """The attribute_staleness_map COMMENT text from the schema-file DDL (source of truth).

    Extracts the single-quoted SQL literal and un-doubles embedded quotes to the logical
    text ``col_description`` returns.
    """
    sql = _SCHEMA_FILE.read_text(encoding="utf-8")
    match = re.search(
        r"COMMENT ON COLUMN canonical\.store_sku_current_position\.attribute_staleness_map IS\s*'(.*?)';",
        sql,
        re.DOTALL,
    )
    assert match is not None, "attribute_staleness_map COMMENT not found in the schema file"
    return match.group(1).replace("''", "'")


def _column_comment(engine: Engine) -> str | None:
    """The live column comment via col_description (None when unset)."""
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT col_description(c.oid, a.attnum) "
                "FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_attribute a ON a.attrelid = c.oid "
                "WHERE n.nspname = :s AND c.relname = :t AND a.attname = :col"
            ),
            {"s": _SCHEMA, "t": _TABLE, "col": _COL},
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


# --- The migration constant is pinned to the schema file (drift guard, no DB) --


def test_migration_new_comment_matches_the_schema_file() -> None:
    """The load-bearing anti-drift pin: the migration's _NEW_COMMENT is byte-identical to
    the schema-file COMMENT. If they diverge, fresh (schema file via 0001) and the 0015
    override would disagree on intent even while the DB looks consistent."""
    mod = _load_migration_module()
    assert mod._NEW_COMMENT == _schema_file_comment()


# --- Comment reconciled at head (resident, read-only) -------------------------


def test_resident_comment_matches_schema_file_at_head(admin_engine: Engine) -> None:
    """The resident DB (at head via make run-local) carries the reconciled column comment,
    equal to the schema-file text (== the Slice 50d set) — schema-file == migration constant
    == resident DB. Read-only: no alembic runs against the resident DB."""
    live = _column_comment(admin_engine)
    assert live == _schema_file_comment()
    assert live is not None
    assert "current_retail_price, unit_cost, stock_qty, expiry_date" in live
    # The retired columns and the stale promo_price are gone from the reconciled comment.
    assert "promo_price" not in live
    assert "sku_status" not in live


# --- Fresh == migrated --------------------------------------------------------


def test_fresh_bootstrap_converges_with_delta_path(scratch_db: ScratchDB, admin_engine: Engine) -> None:
    """The full chain upgrades clean to head and lands the IDENTICAL comment on a fresh
    scratch DB as the resident migrated reference carries (fresh == migrated)."""
    delta = _column_comment(admin_engine)
    assert delta == _schema_file_comment()

    with scratch_db.engine.connect() as conn:
        head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert head == alembic_head()
    fresh = _column_comment(scratch_db.engine)
    assert fresh == delta, (
        "fresh bootstrap produced a different attribute_staleness_map comment than the "
        "migrated reference — the DDL file and migration 0015 disagree (fresh != migrated)"
    )


# --- Downgrade round-trip: deferred until staging (D99) -----------------------


@pytest.mark.skip(reason="downgrade-reversibility deferred until staging (D99)")
def test_downgrade_restores_then_reupgrade_reapplies(scratch_db: ScratchDB) -> None:
    """Round-trip on a scratch DB: head (new text) -> downgrade 0014 (pre-slice text) -> head
    (new text). Skipped under D99; the downgrade leg is authored in the migration."""
    mod = _load_migration_module()
    scratch_db.alembic("upgrade", "head")
    scratch_db.alembic("downgrade", "0014")
    assert _column_comment(scratch_db.engine) == mod._OLD_COMMENT
    scratch_db.alembic("upgrade", "head")
    assert _column_comment(scratch_db.engine) == mod._NEW_COMMENT
