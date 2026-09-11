"""Migration 0012 (nullable hot columns: unit_cost, product_category).

Proves, against the resident DIS database (5433 / ithina_dis_db, read-only
reference) and an ephemeral scratch DB:

  * **Target-safety guard** (pure, always-run, never skips): refuses Customer Master
    and any non-DIS database; passes the DIS database.
  * **Nullable at head** (the headline schema effect): at head, both
    canonical.store_sku_current_position.unit_cost and .product_category are NULLABLE,
    and ck_sscp_unit_cost_non_negative is RETAINED (NULL-safe, not dropped).
  * **Fresh == migrated** on a scratch DB: 0001 applies the edited DDL files (already
    nullable), so a fresh bootstrap to head lands the identical nullability the delta
    path leaves.

Downgrade-reversibility (the SET NOT NULL round-trip) is deferred until staging:
the downgrade leg is authored in the migration, but its round-trip test is skipped with
the shared, greppable reason.

See: the 0011 fresh==migrated precedent.
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
_MIGRATION_PATH = _REPO_ROOT / "alembic" / "versions" / "0012_nullable_hot_unit_cost_product_category.py"

_SCHEMA = "canonical"
_TABLE = "store_sku_current_position"
_TARGET_COLUMNS = ("unit_cost", "product_category")
_UNIT_COST_CHECK = "ck_sscp_unit_cost_non_negative"


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0012", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


# --- Introspection helpers ----------------------------------------------------


def _nullability(engine: Engine, columns: tuple[str, ...]) -> dict[str, str]:
    """Map each target column to its information_schema is_nullable ('YES'/'NO')."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = :t AND column_name = ANY(:cols)"
            ),
            {"s": _SCHEMA, "t": _TABLE, "cols": list(columns)},
        ).all()
    return {row.column_name: row.is_nullable for row in rows}


def _check_present(engine: Engine, conname: str) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_constraint "
                    f"WHERE conrelid = '{_SCHEMA}.{_TABLE}'::regclass "  # noqa: S608 — fixed identifiers
                    "AND contype = 'c' AND conname = :c)"
                ),
                {"c": conname},
            ).scalar_one()
        )


# --- Nullable-at-head + CHECK retained (resident, read-only) ------------------


def test_both_columns_nullable_at_head_and_check_retained(admin_engine: Engine) -> None:
    """The headline schema effect: both targets NULLABLE at head, unit_cost CHECK kept.
    Read against the resident DB (at head via make run-local, read-only)."""
    nullability = _nullability(admin_engine, _TARGET_COLUMNS)
    assert nullability == {"unit_cost": "YES", "product_category": "YES"}, (
        f"expected both targets nullable at head, got {nullability}"
    )
    assert _check_present(admin_engine, _UNIT_COST_CHECK), (
        f"{_UNIT_COST_CHECK} was dropped — it is NULL-safe and must be retained"
    )


# --- Fresh == migrated --------------------------------------------------------


def test_fresh_bootstrap_converges_with_delta_path(scratch_db: ScratchDB, admin_engine: Engine) -> None:
    """The fresh path (the scratch DB where 0001 applies the edited nullable DDL and
    0012's DROP NOT NULL is a no-op) lands the IDENTICAL nullability the delta path (the
    resident migrated reference) leaves at head — and the unit_cost CHECK is present on
    both paths (fresh == migrated)."""
    delta = _nullability(admin_engine, _TARGET_COLUMNS)
    assert delta == {"unit_cost": "YES", "product_category": "YES"}

    with scratch_db.engine.connect() as conn:
        head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert head == alembic_head()
    fresh = _nullability(scratch_db.engine, _TARGET_COLUMNS)
    assert fresh == delta, (
        "fresh bootstrap produced different nullability than the migrated path — "
        "the DDL files and migration 0012 disagree (fresh != migrated)"
    )
    assert _check_present(scratch_db.engine, _UNIT_COST_CHECK), (
        "fresh bootstrap is missing the unit_cost CHECK present on the migrated path"
    )


# --- Downgrade round-trip: deferred until staging -----------------------


@pytest.mark.skip(reason="downgrade-reversibility deferred until staging (D99)")
def test_downgrade_restores_not_null_then_reupgrade(scratch_db: ScratchDB) -> None:
    """Round-trip on the scratch DB: head (nullable) -> downgrade 0011 (SET NOT NULL)
    -> head (nullable). Skipped under D99; the downgrade leg is authored in the migration."""
    scratch_db.alembic("downgrade", "0011")
    restored = _nullability(scratch_db.engine, _TARGET_COLUMNS)
    assert restored == {"unit_cost": "NO", "product_category": "NO"}
    scratch_db.alembic("upgrade", "head")
    assert _nullability(scratch_db.engine, _TARGET_COLUMNS) == {"unit_cost": "YES", "product_category": "YES"}
