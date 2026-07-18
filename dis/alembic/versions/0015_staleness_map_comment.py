"""reconcile attribute_staleness_map column comment to the Slice 50d set — Slice 50d

Comment-only migration: updates the ``COMMENT ON COLUMN`` text on
``canonical.store_sku_current_position.attribute_staleness_map`` to match the edited
schema-file DDL (Slice 50d), so the live migrated DB comment == the fresh-bootstrap
comment. NO column, type, nullability, constraint, index, partition, role, trigger, or
policy is touched — no data, no lock concern (a metadata catalog update).

Why a migration for a comment: this repo DOES reconcile column-comment text in the
fresh==migrated invariant where a migration sets it (the 0005 precedent reconciles
``col_description``/``obj_description`` for config.source_mappings and issues
unconditional COMMENT statements). Slice 50d changes the published tracked set
(current_retail_price, unit_cost, stock_qty, expiry_date) and the merge/write-presence
semantics; without this migration the live DB comment would stay the stale pre-slice text
(fresh != migrated for the comment). The 50a change-stamp comments were left un-migrated
(0014 added the columns with no COMMENT); that gap is out of scope here.

- upgrade(): one ``COMMENT ON COLUMN … IS '<new text>'``. Idempotent by nature (it sets
  text): on the fresh bootstrap path 0001 already applied the edited DDL's new comment, so
  re-setting the identical text here is a harmless no-op → fresh == migrated. On an
  existing migrated DB it replaces the stale text.
- downgrade(): one ``COMMENT ON COLUMN … IS '<pre-slice text>'`` restoring the prior
  comment verbatim.

dbt/BigQuery (the 4th step of the dis-canonical coordinated-change contract) is a NO-OP:
there is no BigQuery mirror for store_sku_current_position.

Fresh == migrated: proven by tests/integration/test_migration_0015.py (comment-text
convergence, mirroring the 0014 scratch-DB harness and the 0005 comment reconciliation).

See: docs/slices/slice-50d-staleness-map-rework.md, the 0005 COMMENT-reconciliation
precedent, the 0014 fresh==migrated scratch-DB precedent.

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-12

"""

from __future__ import annotations

import os

from alembic import op

# revision identifiers, used by Alembic.
revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

# Target-safety guard (Slice 1 §A.2 pattern, copied from 0001..0014).
_EXPECTED_DB = os.environ.get("POSTGRES_DB", "ithina_dis_db")
_CM_DB = "ithina_platform_db"

_COLUMN = "canonical.store_sku_current_position.attribute_staleness_map"

# The two comment texts, verbatim (single quotes are doubled at SQL-build time). The NEW
# text MUST match schemas/postgres/canonical/store_sku_current_position.sql exactly, or the
# fresh==migrated comment convergence test fails.
_NEW_COMMENT = (
    "Per-attribute freshness map. JSONB object keyed by column name, values are ISO 8601 "
    "UTC timestamps. Catalogue-path tracked set (Slice 50d): current_retail_price, "
    "unit_cost, stock_qty, expiry_date. Semantics are write-presence, not value-change: a "
    "key advances to the write's received_ts whenever that column is carried by a "
    "catalogue upsert (even if the value is unchanged) — distinct from the *_changed_at "
    "columns, which advance only on real change. Maintained per-column by MERGE (jsonb ||): "
    "a write updates only the keys it carries and preserves every other stored key; a "
    "column never carried has no key. Only the catalogue path maintains this today; the "
    "event paths do not touch it. Compute-owned velocity_7day/stock_age_days/"
    "unit_cost_trend_30day are DEFERRED (no hot-table writer until daily-compute exists). "
    "Database does not enforce shape; streaming consumer is responsible."
)
_OLD_COMMENT = (
    "Per-attribute freshness map. JSONB object keyed by column name, values are ISO 8601 "
    "UTC timestamps. Initial tracked set: stock_qty, current_retail_price, unit_cost, "
    "promo_price, velocity_7day, stock_age_days, unit_cost_trend_30day. Designed to evolve. "
    "Database does not enforce shape; streaming consumer is responsible."
)


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


def _comment_sql(comment: str) -> str:
    """A single ``COMMENT ON COLUMN`` statement; single quotes doubled for the SQL literal.

    COMMENT ON does not accept bind parameters, so the text is inlined as a literal.
    """
    escaped = comment.replace("'", "''")
    return f"COMMENT ON COLUMN {_COLUMN} IS '{escaped}'"


def upgrade() -> None:
    _guard_target()
    op.get_bind().exec_driver_sql(_comment_sql(_NEW_COMMENT))


def downgrade() -> None:
    _guard_target()
    op.get_bind().exec_driver_sql(_comment_sql(_OLD_COMMENT))
