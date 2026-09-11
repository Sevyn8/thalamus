"""Migration 0014 (per-attribute change-signal columns on store_sku_current_position).

Proves, against the resident DIS database (5433 / ithina_dis_db, read-only
reference) and an ephemeral scratch DB:

  * **Target-safety guard** (pure, always-run, never skips): refuses Customer Master
    and any non-DIS database; passes the DIS database.
  * **Both columns present + nullable at head** (the headline schema effect): at head,
    canonical.store_sku_current_position gains current_retail_price_changed_at and
    product_name_changed_at, both TIMESTAMPTZ and NULLABLE, and empty (50a writes nothing).
  * **Fresh == migrated** on a scratch DB: 0001 applies the edited DDL files (columns
    already present), and 0014's ADD COLUMN IF NOT EXISTS is a no-op, so a fresh bootstrap
    to head lands the identical two columns with identical nullability the delta path leaves.

Downgrade-reversibility (the DROP/re-ADD round-trip) is deferred until staging: the
downgrade leg is authored in the migration, but its round-trip test is skipped with the
shared, greppable reason.

See: the 0012 fresh==migrated precedent.
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
_MIGRATION_PATH = _REPO_ROOT / "alembic" / "versions" / "0014_current_position_change_stamps.py"

_SCHEMA = "canonical"
_TABLE = "store_sku_current_position"
_TARGET_COLUMNS = ("current_retail_price_changed_at", "product_name_changed_at")


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0014", _MIGRATION_PATH)
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


def _column_shapes(engine: Engine, columns: tuple[str, ...]) -> dict[str, tuple[str, str]]:
    """Map each target column to (data_type, is_nullable). Missing columns are absent."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = :t AND column_name = ANY(:cols)"
            ),
            {"s": _SCHEMA, "t": _TABLE, "cols": list(columns)},
        ).all()
    return {row.column_name: (row.data_type, row.is_nullable) for row in rows}


# --- Both columns present + nullable at head (resident, read-only) ------------


def test_both_columns_present_nullable_timestamptz_at_head(admin_engine: Engine) -> None:
    """The headline schema effect: both targets present, TIMESTAMPTZ, NULLABLE at head.
    Read against the resident DB (at head via make run-local, read-only)."""
    shapes = _column_shapes(admin_engine, _TARGET_COLUMNS)
    assert shapes == {
        "current_retail_price_changed_at": ("timestamp with time zone", "YES"),
        "product_name_changed_at": ("timestamp with time zone", "YES"),
    }, f"expected both change-signal columns present as nullable timestamptz, got {shapes}"


def test_columns_are_empty_after_migration(admin_engine: Engine) -> None:
    """50a writes nothing: no row carries a non-NULL value for either column.
    Read against the resident DB (read-only)."""
    with admin_engine.connect() as conn:
        non_null = conn.execute(
            text(
                f"SELECT count(*) FROM {_SCHEMA}.{_TABLE} "  # noqa: S608 — fixed identifiers
                "WHERE current_retail_price_changed_at IS NOT NULL "
                "OR product_name_changed_at IS NOT NULL"
            )
        ).scalar_one()
    assert non_null == 0, "50a must not stamp any value; a non-NULL change-signal appeared"


# --- Fresh == migrated --------------------------------------------------------


def test_fresh_bootstrap_converges_with_delta_path(scratch_db: ScratchDB, admin_engine: Engine) -> None:
    """The fresh path (the scratch DB where 0001 applies the edited DDL with both columns
    and 0014's ADD COLUMN IF NOT EXISTS is a no-op) lands the IDENTICAL two columns /
    nullability the delta path (the resident migrated reference) leaves at head
    (fresh == migrated)."""
    delta = _column_shapes(admin_engine, _TARGET_COLUMNS)
    assert delta == {
        "current_retail_price_changed_at": ("timestamp with time zone", "YES"),
        "product_name_changed_at": ("timestamp with time zone", "YES"),
    }

    with scratch_db.engine.connect() as conn:
        head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert head == alembic_head()
    fresh = _column_shapes(scratch_db.engine, _TARGET_COLUMNS)
    assert fresh == delta, (
        "fresh bootstrap produced different change-signal columns than the migrated "
        "path — the DDL files and migration 0014 disagree (fresh != migrated)"
    )


# --- Downgrade round-trip: deferred until staging -----------------------


@pytest.mark.skip(reason="downgrade-reversibility deferred until staging (D99)")
def test_downgrade_drops_then_reupgrade_readds(scratch_db: ScratchDB) -> None:
    """Round-trip on the scratch DB: head (present) -> downgrade 0013 (dropped) -> head
    (present). Skipped under D99; the downgrade leg is authored in the migration."""
    scratch_db.alembic("downgrade", "0013")
    assert _column_shapes(scratch_db.engine, _TARGET_COLUMNS) == {}
    scratch_db.alembic("upgrade", "head")
    assert _column_shapes(scratch_db.engine, _TARGET_COLUMNS) == {
        "current_retail_price_changed_at": ("timestamp with time zone", "YES"),
        "product_name_changed_at": ("timestamp with time zone", "YES"),
    }
