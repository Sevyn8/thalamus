"""per-attribute change-signal columns on store_sku_current_position — Slice 50a

Adds two nullable per-attribute "last changed" signal columns to the current-position
hot table: ``current_retail_price_changed_at`` and ``product_name_changed_at`` (both
``TIMESTAMPTZ NULL``). 50a only makes them exist and classifies them compute-owned
(``libs/dis-validation/provenance.py``); it writes and stamps NOTHING. The catalogue-
upsert maintenance that advances them is Slice 50b (separate commit).

"Compute-owned" here = consumer-maintained at write by the catalogue path in 50b, NOT a
daily-compute job (no such job exists or is planned for these). They are deliberately NOT
mapping_produced, so they never enter the source-mapped set or the write-time completeness
required-set (``mandatory_mapping_produced``) — routing is unchanged.

- upgrade(): two ``ADD COLUMN IF NOT EXISTS … TIMESTAMPTZ`` (inline SQL; never re-reads the
  DDL files at runtime). ``IF NOT EXISTS`` is the fresh==migrated mechanism: on the fresh
  bootstrap path 0001 applies the edited DDL (columns already present), so this ADD is a
  no-op; on an existing migrated DB it adds them. No other column, constraint, index,
  partition, role, trigger, or policy is touched.
- downgrade(): two ``DROP COLUMN IF EXISTS`` restoring the pre-slice form.

dbt/BigQuery (the 4th step of the dis-canonical coordinated-change contract) is a NO-OP
here: there is no BigQuery mirror for store_sku_current_position (schemas/bigquery/ holds
only canonical_history_* for sale_events / change_events / signal_history). No dbt model
to change.

Fresh == migrated: proven by tests/integration/test_migration_0014.py (mirrors the 0012
precedent).

See: docs/slices/slice-50a-change-stamp-columns.md, docs/scratch/slice-50a-plan.md,
docs/scratch/esl-stamp-risk.md, the 0003 ADD COLUMN IF NOT EXISTS precedent, the 0012
fresh==migrated precedent.

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-11

"""

from __future__ import annotations

import os

from alembic import op

# revision identifiers, used by Alembic.
revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

# Target-safety guard (Slice 1 §A.2 pattern, copied from 0001..0012).
_EXPECTED_DB = os.environ.get("POSTGRES_DB", "ithina_dis_db")
_CM_DB = "ithina_platform_db"

_TABLE = "canonical.store_sku_current_position"
# The two columns this slice adds; the only schema mutation in either direction.
_COLUMNS = ("current_retail_price_changed_at", "product_name_changed_at")


def check_migration_target(current: str, *, expected_db: str = _EXPECTED_DB, cm_db: str = _CM_DB) -> None:
    """Pure target check: refuse Customer Master outright, require the DIS database."""
    if current == cm_db:
        raise RuntimeError(
            f"Refusing to run DIS migration: connected to the Customer Master "
            f"database '{current}'. Point POSTGRES_ADMIN_URL at the DIS database."
        )
    if current != expected_db:
        raise RuntimeError(
            f"Refusing to run DIS migration: connected to '{current}' but expected "
            f"DIS database '{expected_db}' (POSTGRES_DB). Check POSTGRES_ADMIN_URL."
        )


def _guard_target() -> None:
    current = op.get_bind().exec_driver_sql("SELECT current_database()").scalar()
    check_migration_target(str(current))


def _exec(sql: str) -> None:
    """Raw DBAPI execution (the DDL idiom shared with 0001/0011/0012)."""
    op.get_bind().exec_driver_sql(sql)


def upgrade() -> None:
    _guard_target()
    # Add exactly the two nullable change-signal columns. IF NOT EXISTS makes this a
    # no-op on the fresh/bootstrap path (0001 already created them from the edited DDL).
    for column in _COLUMNS:
        _exec(f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS {column} TIMESTAMPTZ")


def downgrade() -> None:
    _guard_target()
    for column in _COLUMNS:
        _exec(f"ALTER TABLE {_TABLE} DROP COLUMN IF EXISTS {column}")
