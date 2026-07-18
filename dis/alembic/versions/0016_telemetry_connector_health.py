"""telemetry.connector_health: Connector Health Phase A — worker-produced telemetry — D116

Introduces the telemetry schema (schema #8) and telemetry.connector_health, the first
WORKER-PRODUCED telemetry table in the shared DIS DB. One row per (tenant_id, source_id),
FK to identity_mirror.tenants, two-GUC RLS (USING tenant OR PLATFORM; WITH CHECK tenant-pin),
carrying last_seen_at / last_error_at / last_error_detail / auth_expires_at / rate_limit_state /
missed_intervals / status (all NULLABLE). STANDALONE — no FK from source_id to config.sources
(joined at read, D116). Resolves the deferral D112 flagged.

- upgrade():
  1. CREATE SCHEMA telemetry (schema #8; NOT added to the 0001 bootstrap SCHEMAS list, and
     the DDL file is NOT in the 0001 MANIFEST — so 0016 is the SOLE creator and
     fresh(0001..0016) == migrated, the sole-creator invariant established by 0013/D112).
  2. GRANT USAGE on the schema to the app role + ALTER DEFAULT PRIVILEGES (mirror the 0001
     bootstrap grants block for a brand-new schema).
  3. apply schemas/postgres/telemetry/connector_health.sql verbatim (table + RLS policy).
  4. explicit table GRANT to the app role (belt over the default-privileges inheritance).

  NO backfill: health is LIVE-EMITTED by the worker, not reconstructable from history
  (unlike the 0013 config.sources backfill). NO FK to config.sources (join at read).

- downgrade(): DROP SCHEMA telemetry CASCADE (drops the table, its policy, indexes). The
  round-trip test is skipped per D99 (downgrade-reversibility deferred to staging).

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-13

"""

from __future__ import annotations

import os
from pathlib import Path

from alembic import op

# revision identifiers, used by Alembic.
revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

# Target-safety guard (Slice 1 §A.2 pattern, copied from 0001..0015).
_EXPECTED_DB = os.environ.get("POSTGRES_DB", "ithina_dis_db")
_CM_DB = "ithina_platform_db"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DDL_FILE = _REPO_ROOT / "schemas" / "postgres" / "telemetry" / "connector_health.sql"
_APP_ROLE = "ithina_dis_user"
_SCHEMA = "telemetry"


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
    """Raw DBAPI execution (the DDL idiom shared with 0001/0011/0012/0013)."""
    op.get_bind().exec_driver_sql(sql)


def upgrade() -> None:
    _guard_target()
    # 1. Create the NEW telemetry schema (0016 is the sole creator; not in the 0001 manifest).
    _exec(f'CREATE SCHEMA IF NOT EXISTS "{_SCHEMA}"')
    # 2. Grant the NOBYPASSRLS app role usage + default privileges on the new schema
    #    (mirror the 0001 bootstrap grants block for a brand-new schema).
    _exec(f'GRANT USAGE ON SCHEMA "{_SCHEMA}" TO {_APP_ROLE}')
    _exec(
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{_SCHEMA}" '
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {_APP_ROLE}"
    )
    # 3. Create the table + RLS policy from the DDL file (verbatim, like the bootstrap).
    _exec(_DDL_FILE.read_text())
    # 4. Explicit table grant (belt over the ALTER DEFAULT PRIVILEGES inheritance).
    _exec(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_SCHEMA}.connector_health TO {_APP_ROLE}")


def downgrade() -> None:
    _guard_target()
    _exec(f'DROP SCHEMA IF EXISTS "{_SCHEMA}" CASCADE')
