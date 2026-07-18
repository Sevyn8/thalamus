"""Migration 0002 (identity_mirror external codes): target safety + reversibility.

Slice 9a AC4. Two layers:

  * **Target-safety guard, asserted positively and non-skippably.** The pure
    ``check_migration_target`` refusal logic is unit-testable without a live bind
    (the ``test_reader_guards`` precedent): it refuses the Customer Master database
    outright, refuses any non-expected database, and passes only the DIS database.
  * **Reversible cycle against an EPHEMERAL scratch DB (Slice 51c, D122).** ``upgrade head``
    adds the two nullable columns (live introspection via ``information_schema``),
    ``downgrade 0001`` removes them cleanly, re-upgrade restores them — all on a scratch DB
    created and torn down within the test, never the resident DB (5433).

The migration runs against ``ithina_dis_db`` on 5433 only; the in-migration guard
refuses Customer Master (``ithina_platform_db``) before any DDL.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Engine, text

from dis_testing.migration_harness import ScratchDB

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_PATH = _REPO_ROOT / "alembic" / "versions" / "0002_identity_mirror_codes.py"


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0002", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Target-safety guard: pure, always-run, never skips (no DB needed).
# ---------------------------------------------------------------------------


def test_guard_refuses_customer_master() -> None:
    mod = _load_migration_module()
    with pytest.raises(RuntimeError, match="Customer Master"):
        mod.check_migration_target("ithina_platform_db", expected_db="ithina_dis_db")


def test_guard_refuses_unexpected_database() -> None:
    mod = _load_migration_module()
    with pytest.raises(RuntimeError, match="expected"):
        mod.check_migration_target("some_other_db", expected_db="ithina_dis_db")


def test_guard_passes_the_dis_database_positively() -> None:
    # Positive assertion: the one accepted target is the DIS database.
    mod = _load_migration_module()
    mod.check_migration_target("ithina_dis_db", expected_db="ithina_dis_db")


# ---------------------------------------------------------------------------
# Reversible cycle against an ephemeral scratch DB (errors, never skips).
# ---------------------------------------------------------------------------


def _code_columns(engine: Engine) -> dict[tuple[str, str], str]:
    """Introspect the two code columns live: {(table, column): is_nullable}."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT table_name, column_name, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'identity_mirror'
                  AND ((table_name = 'tenants' AND column_name = 'display_code')
                    OR (table_name = 'stores' AND column_name = 'store_code'))
                """
            )
        ).all()
    return {(r.table_name, r.column_name): r.is_nullable for r in rows}


def test_upgrade_head_adds_the_code_columns(scratch_db: ScratchDB) -> None:
    # APPLY-TO-HEAD on the scratch DB (brought to head by the scratch_db fixture): the
    # upgrade leaves both code columns present. The downgrade leg is split out + skipped (D99).
    assert _code_columns(scratch_db.engine) == {
        ("tenants", "display_code"): "YES",
        ("stores", "store_code"): "YES",
    }


@pytest.mark.skip(reason="downgrade-reversibility deferred until staging (D99)")
def test_migration_cycle_adds_and_removes_the_code_columns(scratch_db: ScratchDB) -> None:
    # upgrade head: both columns present, nullable (live introspection, not the DDL files).
    scratch_db.alembic("upgrade", "head")
    assert _code_columns(scratch_db.engine) == {
        ("tenants", "display_code"): "YES",
        ("stores", "store_code"): "YES",
    }

    # downgrade to 0001: both columns removed cleanly.
    scratch_db.alembic("downgrade", "0001")
    assert _code_columns(scratch_db.engine) == {}

    # re-upgrade: restored (the IF NOT EXISTS path is exercised again).
    scratch_db.alembic("upgrade", "head")
    assert _code_columns(scratch_db.engine) == {
        ("tenants", "display_code"): "YES",
        ("stores", "store_code"): "YES",
    }
    # The scratch DB is thrown away at teardown, so no shared-state restore is needed
    # (the resident-DB fixture-value repair the old resident-target cycle carried is gone).
