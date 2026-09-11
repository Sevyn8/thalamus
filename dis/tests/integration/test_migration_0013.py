"""Migration 0013 (config.sources registry) — target safety + idempotency.

Proves, against an ephemeral scratch DB:

  * **Target-safety guard** (pure, always-run, never skips): refuses Customer Master and any
    non-DIS database; passes the DIS database.
  * **Creates config.sources on a fresh DB (AC5 — unchanged fresh behaviour).** A fresh scratch
    DB brought to head carries config.sources with its two-GUC RLS policy — the existence gate
    does NOT skip creation when the object is genuinely absent.
  * **Re-runnable via the REAL alembic path (AC3, D123).** ``alembic stamp 0012`` rewinds only
    the version table (no DDL; config.sources stays), so ``upgrade 0013`` re-runs
    ``0013.upgrade()`` against a DB that ALREADY has the table. Before the D123 existence gate,
    the verbatim ``CREATE TABLE`` would fail "relation already exists" and alembic would exit
    non-zero. A clean re-run leaving the table byte-identical is therefore proof the gate fired.
    The re-application is driven through alembic (the path that actually corrupted the resident
    DB), not a direct Python call to ``upgrade()``.

Downgrade-reversibility is deferred until staging; the downgrade leg is authored in the
migration. Only migration 0013 is gated this slice — other non-idempotent migrations (e.g. 0016
telemetry.connector_health) are surfaced, not fixed (deferred trigger, no D-number).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest
from sqlalchemy import Engine, text

from dis_testing.migration_harness import ScratchDB, alembic_head

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_PATH = _REPO_ROOT / "alembic" / "versions" / "0013_config_sources_registry.py"

_RELATION = "config.sources"
_SCHEMA = "config"
_TABLE = "sources"


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0013", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sources_shape(engine: Engine) -> dict[str, object]:
    """Existence + full normalized shape of config.sources: columns, constraints, indexes, and
    RLS policies — the structural surface 0013's DDL creates."""
    shape: dict[str, object] = {}
    with engine.connect() as conn:
        shape["exists"] = conn.execute(text("SELECT to_regclass(:r)"), {"r": _RELATION}).scalar() is not None
        shape["columns"] = [
            tuple(r)
            for r in conn.execute(
                text(
                    "SELECT column_name, data_type, udt_name, is_nullable, "
                    "COALESCE(character_maximum_length, -1), COALESCE(column_default, '') "
                    "FROM information_schema.columns "
                    "WHERE table_schema = :s AND table_name = :t ORDER BY column_name"
                ),
                {"s": _SCHEMA, "t": _TABLE},
            ).all()
        ]
        shape["constraints"] = {
            str(r[0]): str(r[1])
            for r in conn.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = CAST(:r AS regclass) ORDER BY conname"
                ),
                {"r": _RELATION},
            ).all()
        }
        shape["indexes"] = {
            str(r[0]): str(r[1])
            for r in conn.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE schemaname = :s AND tablename = :t ORDER BY indexname"
                ),
                {"s": _SCHEMA, "t": _TABLE},
            ).all()
        }
        shape["policies"] = {
            str(r[0]): (str(r[1]), str(r[2]))
            for r in conn.execute(
                text(
                    "SELECT polname, pg_get_expr(polqual, polrelid), "
                    "COALESCE(pg_get_expr(polwithcheck, polrelid), '') "
                    "FROM pg_policy WHERE polrelid = CAST(:r AS regclass) ORDER BY polname"
                ),
                {"r": _RELATION},
            ).all()
        }
    return shape


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


# --- Fresh DB creates config.sources (AC5: unchanged fresh behaviour) ---------


def test_0013_creates_config_sources_on_a_fresh_db(scratch_db: ScratchDB) -> None:
    """A fresh scratch DB at head carries config.sources with columns + the two-GUC RLS policy.
    The existence gate does not suppress creation when the object is genuinely absent."""
    with scratch_db.engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == alembic_head()
    shape = _sources_shape(scratch_db.engine)
    assert shape["exists"], "config.sources missing on a fresh DB at head — 0013 did not create it"
    columns = cast("list[tuple[object, ...]]", shape["columns"])
    policies = cast("dict[str, object]", shape["policies"])
    column_names = {row[0] for row in columns}
    assert {"tenant_id", "source_id", "display_name", "channel", "status"} <= column_names
    assert "tenant_isolation" in policies


# --- Re-runnable via the real alembic path (AC3, D123) ------------------------


def test_reapplying_0013_via_alembic_is_a_noop(scratch_db: ScratchDB) -> None:
    """Re-applying 0013 against a DB that already has config.sources is a safe no-op.

    ``stamp 0012`` rewinds only the version table (config.sources stays); ``upgrade 0013``
    re-runs 0013.upgrade(). If the existence gate did not fire, the verbatim CREATE TABLE would
    raise "already exists" and alembic would exit non-zero (``scratch_db.alembic`` would raise).
    A clean re-run leaving the table byte-identical is proof the gate short-circuited the CREATE.
    """
    before = _sources_shape(scratch_db.engine)
    assert before["exists"], "precondition: config.sources present at head"

    scratch_db.alembic("stamp", "0012")  # rewind version only; the table is untouched
    scratch_db.alembic("upgrade", "0013")  # re-runs 0013.upgrade(); gate no-ops the CREATE

    after = _sources_shape(scratch_db.engine)
    assert after == before, "re-applying 0013 changed config.sources — the existence gate did not hold"
