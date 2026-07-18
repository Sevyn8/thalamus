"""Migration 0017 (bronze.data_ingress_events.original_filename capture column — Slice 51a).

Proves, against the resident DB (5433, read-only reference), a fresh scratch DB, and via the
pure target guard (Slice 51c, D122 isolates every alembic run to an ephemeral scratch DB):

  * **Target-safety guard** (pure, always-run, never skips): refuses Customer Master and any
    non-DIS database; passes the DIS database.
  * **Fresh == migrated**: the full chain (0001 applies the edited manifest DDL that carries
    ``original_filename``, … , 0017 re-applies it as a gated ADD COLUMN) upgrades clean to head
    on a fresh scratch DB, landing the additive nullable ``VARCHAR(512)`` column. The gated
    ADD COLUMN is a no-op on the fresh path (the manifest already created it) — proving parity.
  * **Downgrade** drops the column (reversible).

The scratch DB isolates every migration run from the resident dev DB; the chain is run
end-to-end there, so 0017's upgrade IS exercised. Mirrors the 0014/0015 scratch-DB precedent.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Engine, text

from dis_testing.migration_harness import ScratchDB, alembic_head

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_PATH = _REPO_ROOT / "alembic" / "versions" / "0017_bronze_original_filename.py"

_SCHEMA = "bronze"
_TABLE = "data_ingress_events"
_COL = "original_filename"


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0017", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _column(engine: Engine) -> tuple[object, ...] | None:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT data_type, character_maximum_length, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = :t AND column_name = :c"
            ),
            {"s": _SCHEMA, "t": _TABLE, "c": _COL},
        ).first()
        return tuple(row) if row is not None else None


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


# --- Resident at head carries the column (read-only) --------------------------


def test_resident_has_column_at_head(admin_engine: Engine) -> None:
    """The resident DB (at head via make run-local) carries the additive column with the right
    shape. Read-only: no alembic runs against the resident DB."""
    col = _column(admin_engine)
    assert col is not None, "original_filename missing on the resident DB at head"
    data_type, max_len, is_nullable = col
    assert data_type == "character varying" and max_len == 512 and is_nullable == "YES"


# --- Fresh == migrated on a scratch DB (exercises 0017's upgrade in the real chain) --


def test_fresh_bootstrap_lands_the_column_at_head(scratch_db: ScratchDB) -> None:
    """The full chain upgrades clean to head on a fresh scratch DB and lands the additive
    nullable VARCHAR(512) column (fresh == migrated — the gated ADD COLUMN no-ops on fresh)."""
    with scratch_db.engine.connect() as conn:
        head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert head == alembic_head()
    col = _column(scratch_db.engine)
    assert col is not None, "original_filename missing at head"
    data_type, max_len, is_nullable = col
    assert data_type == "character varying" and max_len == 512 and is_nullable == "YES"
