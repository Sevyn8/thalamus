"""config.sources: Phase A source registry + backfill — D112

Introduces config.sources, the first real per-source ENTITY and the first writable
table dis-ui-server owns in the shared DB. One row per (tenant_id, source_id), FK to
identity_mirror.tenants, two-GUC RLS (USING tenant OR PLATFORM; WITH CHECK tenant-pin),
carrying display_name, channel (dis_channel vocab, NULLable), store_id?, schedule?,
status. STANDALONE — no FK from config.source_mappings.source_id (deferred, D112).

- upgrade():
  1. apply schemas/postgres/config/sources.sql verbatim (bootstrap-manifest read_text
     idiom; the DDL declares the table + RLS policy). NOT added to the 0001 manifest,
     so 0013 is the sole creator — fresh(0001..0013) == migrated (no double-create).
     GATED ON EXISTENCE (Slice 51c, D123): the file is applied only when config.sources is
     absent, so re-applying 0013 against a DB that already has the table is a safe no-op
     rather than an already-exists failure. On a fresh DB the table is absent, so the file
     is applied verbatim — create-on-fresh behaviour is unchanged, and sources.sql is left
     byte-identical (no IF NOT EXISTS edits, so it cannot drift). This mirrors the
     existence-gate 0017 uses for its ADD COLUMN, applied around the multi-statement file
     read (which cannot sit inside a single DO block).
  2. explicit GRANT to the app role (first post-bootstrap table; belt over the 0001
     ALTER DEFAULT PRIVILEGES inheritance).
  3. BACKFILL: one row per distinct (tenant_id, source_id) in config.source_mappings —
     display_name humanized from the slug, channel best-effort = the most-recent
     dis_channel on that source's bronze.data_ingress_events (NULL if none), status
     'active'. Idempotent via ON CONFLICT DO NOTHING. Runs as the migrating superuser
     (bypasses RLS), so it seeds every tenant's sources in one statement.

- downgrade(): DROP TABLE config.sources (drops its policy + indexes). The round-trip
  test is skipped per D99 (downgrade-reversibility deferred to staging).

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-12

"""

from __future__ import annotations

import os
from pathlib import Path

from alembic import op

# revision identifiers, used by Alembic.
revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

# Target-safety guard (Slice 1 §A.2 pattern, copied from 0001..0012).
_EXPECTED_DB = os.environ.get("POSTGRES_DB", "ithina_dis_db")
_CM_DB = "ithina_platform_db"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DDL_FILE = _REPO_ROOT / "schemas" / "postgres" / "config" / "sources.sql"
_APP_ROLE = "ithina_dis_user"

# Backfill: one config.sources row per distinct source the tenant already has a mapping
# for. channel is best-effort (most-recent bronze dis_channel for that source, else NULL).
_BACKFILL = """
INSERT INTO config.sources (tenant_id, source_id, display_name, channel, status)
SELECT
    sm.tenant_id,
    sm.source_id,
    initcap(replace(sm.source_id, '_', ' ')) AS display_name,
    (
        SELECT b.dis_channel
        FROM bronze.data_ingress_events b
        WHERE b.tenant_id = sm.tenant_id AND b.source_id = sm.source_id
        ORDER BY b.received_at DESC
        LIMIT 1
    ) AS channel,
    'active' AS status
FROM (SELECT DISTINCT tenant_id, source_id FROM config.source_mappings) sm
ON CONFLICT (tenant_id, source_id) DO NOTHING
"""


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


def _sources_table_exists() -> bool:
    """Whether config.sources already exists (the existence gate for idempotency, D123)."""
    return bool(op.get_bind().exec_driver_sql("SELECT to_regclass('config.sources')").scalar())


def upgrade() -> None:
    _guard_target()
    # 1. Create the table + RLS policy from the DDL file (verbatim, like the bootstrap).
    #    Gated on existence (D123): re-applying 0013 where the table already exists is a
    #    no-op, not an already-exists failure. Fresh DB (table absent) -> applied verbatim,
    #    so create-on-fresh is unchanged and sources.sql stays byte-identical.
    if not _sources_table_exists():
        _exec(_DDL_FILE.read_text())
    # 2. Explicit grant for the NOBYPASSRLS app role (first post-bootstrap table).
    _exec(f"GRANT SELECT, INSERT, UPDATE, DELETE ON config.sources TO {_APP_ROLE}")
    # 3. Backfill from existing mappings (idempotent).
    _exec(_BACKFILL)


def downgrade() -> None:
    _guard_target()
    _exec("DROP TABLE IF EXISTS config.sources")
