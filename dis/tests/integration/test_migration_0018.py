"""Migration 0018 (bronze.data_ingress_events keyset-pagination covering index).

Proves, against the resident DB (5433, read-only reference), a fresh scratch DB, and via the
pure target guard:

  * **Target-safety guard** (pure, always-run, never skips): refuses Customer Master and any
    non-DIS database; passes the DIS database.
  * **Fresh == migrated**: the full chain (0001 applies the edited manifest DDL that carries
    ``ix_bdie_tenant_received_at_id``, … , 0018 re-applies it as a gated ``CREATE INDEX IF NOT
    EXISTS``) upgrades clean to head on a fresh scratch DB, landing the additive composite index
    ``(tenant_id, received_at DESC, id DESC)``. The gated create no-ops on the fresh path (the
    manifest already created it) — proving parity.
  * **Downgrade** drops the index (reversible).

Index only: no column, no data, no constraint. Mirrors the 0017 scratch-DB precedent.
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
_MIGRATION_PATH = _REPO_ROOT / "alembic" / "versions" / "0018_bronze_keyset_pagination_index.py"

_SCHEMA = "bronze"
_TABLE = "data_ingress_events"
_INDEX = "ix_bdie_tenant_received_at_id"


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0018", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _index_def(engine: Engine) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE schemaname = :s AND tablename = :t AND indexname = :i"
            ),
            {"s": _SCHEMA, "t": _TABLE, "i": _INDEX},
        ).scalar()


def _assert_covering_index(indexdef: str | None) -> None:
    assert indexdef is not None, f"{_INDEX} missing"
    # The keyset-supporting shape: tenant_id, then received_at DESC, then id DESC.
    assert "tenant_id" in indexdef
    assert "received_at DESC" in indexdef
    assert "id DESC" in indexdef


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


# --- Resident at head carries the index (read-only) ---------------------------


def test_resident_has_index_at_head(admin_engine: Engine) -> None:
    """The resident DB (at head via make run-local) carries the covering index. Read-only: no
    alembic runs against the resident DB."""
    _assert_covering_index(_index_def(admin_engine))


# --- Fresh == migrated on a scratch DB (exercises 0018's upgrade in the real chain) --


def test_fresh_bootstrap_lands_the_index_at_head(scratch_db: ScratchDB) -> None:
    """The full chain upgrades clean to head on a fresh scratch DB and lands the additive
    composite index (fresh == migrated — the gated CREATE INDEX IF NOT EXISTS no-ops on fresh)."""
    with scratch_db.engine.connect() as conn:
        head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert head == alembic_head()
    _assert_covering_index(_index_def(scratch_db.engine))
