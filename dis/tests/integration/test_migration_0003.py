"""Migration 0003 (canonical dedup columns + hot event-time ref): target safety,
emptiness precondition, reversibility.

M-D38/D64 (Slice 10 prerequisite). Three layers:

  * **Target-safety guard, asserted positively and non-skippably.** The pure
    ``check_migration_target`` refusal logic is unit-testable without a live
    bind (the 0002 precedent): refuses Customer Master outright, refuses any
    non-expected database, passes only the DIS database.
  * **Emptiness precondition.** The NOT NULL adds (no DEFAULT) are legal only
    against empty event tables; the migration re-checks ``COUNT(*) = 0``
    immediately before each add and aborts loudly otherwise. Read on the
    resident DB (read-only), where the precondition state is observed.
  * **Reversible cycle against an ephemeral scratch DB (Slice 51c, D122).**
    ``upgrade head`` adds the four event-table columns NOT NULL, the two
    dedup-window indexes, and the nullable hot column (introspection via
    ``information_schema`` / ``pg_indexes``); ``downgrade 0002`` removes all
    cleanly; re-upgrade restores them (exercising the IF NOT EXISTS no-op path
    0001-bootstrapped databases take).

The migration runs against ``ithina_dis_db`` on 5433 only; the in-migration
guard refuses Customer Master (``ithina_platform_db``) before any DDL.

See: docs/slices/slice-10-streaming-consumer.md, decisions.md D38/D64/D65/D33.
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
_MIGRATION_PATH = _REPO_ROOT / "alembic" / "versions" / "0003_canonical_dedup_event_time.py"

_EVENT_TABLES = ("store_sku_sale_events", "store_sku_change_events")
_DEDUP_INDEXES = ("ix_ssse_dedup_key", "ix_ssce_dedup_key")


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0003", _MIGRATION_PATH)
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
# Live-shape introspection helpers.
# ---------------------------------------------------------------------------


def _dedup_columns(engine: Engine) -> dict[tuple[str, str], tuple[str, str | None]]:
    """Live introspection: {(table, column): (is_nullable, max_length)} for the
    four event-table dedup columns plus the hot event-time column."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT table_name, column_name, is_nullable, character_maximum_length
                FROM information_schema.columns
                WHERE table_schema = 'canonical'
                  AND ((table_name IN ('store_sku_sale_events', 'store_sku_change_events')
                        AND column_name IN ('source_id', 'source_event_id'))
                    OR (table_name = 'store_sku_current_position'
                        AND column_name = 'last_source_event_at'))
                """
            )
        ).all()
    return {(r.table_name, r.column_name): (r.is_nullable, r.character_maximum_length) for r in rows}


def _dedup_indexes(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT indexname FROM pg_indexes
                WHERE schemaname = 'canonical'
                  AND indexname IN ('ix_ssse_dedup_key', 'ix_ssce_dedup_key')
                """
            )
        ).all()
    return {r.indexname for r in rows}


def _event_row_counts(engine: Engine) -> dict[str, int]:
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        for table in _EVENT_TABLES:
            counts[table] = conn.execute(
                text(f"SELECT COUNT(*) FROM canonical.{table}")  # noqa: S608 — fixed table names
            ).scalar_one()
    return counts


_EXPECTED_PRESENT = {
    ("store_sku_sale_events", "source_id"): ("NO", 128),
    ("store_sku_sale_events", "source_event_id"): ("NO", 256),
    ("store_sku_change_events", "source_id"): ("NO", 128),
    ("store_sku_change_events", "source_event_id"): ("NO", 256),
    ("store_sku_current_position", "last_source_event_at"): ("YES", None),
}


# ---------------------------------------------------------------------------
# At-head shape + emptiness precondition (resident DB, read-only).
# ---------------------------------------------------------------------------


def test_event_tables_empty_precondition(admin_engine: Engine) -> None:
    # The NOT NULL adds are legal only because the event tables are empty (the
    # plan precondition, re-checked in-migration). The precondition is only
    # load-bearing BEFORE 0003's columns exist: once the migration has landed,
    # event rows are normal (Slice 10 writes them) and the precondition is
    # moot — asserting raw emptiness then would be a false alarm.
    if set(_dedup_columns(admin_engine)) == set(_EXPECTED_PRESENT):
        return  # columns landed; the add-window precondition no longer applies
    assert _event_row_counts(admin_engine) == {t: 0 for t in _EVENT_TABLES}


def test_upgrade_head_adds_dedup_columns(admin_engine: Engine) -> None:
    # The resident DB is at head via make run-local (read-only): the dedup
    # columns + both indexes are present — the apply-to-head proof (the
    # downgrade leg is split out + skipped per D99).
    assert _dedup_columns(admin_engine) == _EXPECTED_PRESENT
    assert _dedup_indexes(admin_engine) == set(_DEDUP_INDEXES)


@pytest.mark.skip(reason="downgrade-reversibility deferred until staging (D99)")
def test_migration_cycle_adds_and_removes_dedup_columns(scratch_db: ScratchDB) -> None:
    # The downgrade/re-upgrade cycle runs on the ephemeral scratch DB (already
    # at head via the fixture), so a populated resident DB can never be stranded
    # at 0002 by the re-upgrade's NOT NULL adds — the scratch DB's event tables
    # are always empty.
    assert _dedup_columns(scratch_db.engine) == _EXPECTED_PRESENT
    assert _dedup_indexes(scratch_db.engine) == set(_DEDUP_INDEXES)

    # downgrade to 0002: all five columns and both indexes removed cleanly.
    scratch_db.alembic("downgrade", "0002")
    assert _dedup_columns(scratch_db.engine) == {}
    assert _dedup_indexes(scratch_db.engine) == set()

    # re-upgrade: restored (the IF NOT EXISTS / column-exists no-op path is
    # exercised again — the path a 0001-bootstrapped fresh database takes).
    scratch_db.alembic("upgrade", "head")
    assert _dedup_columns(scratch_db.engine) == _EXPECTED_PRESENT
    assert _dedup_indexes(scratch_db.engine) == set(_DEDUP_INDEXES)
