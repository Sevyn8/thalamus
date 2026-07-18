"""bronze.data_ingress_events: original_filename capture column (Slice 51a)

The single additive DDL of Slice 51a (D120): bronze persists the uploaded file's ORIGINAL name
so the Ingestion Runs surface can show it. Today dis-ui-server parses the multipart filename
(``upload_stream.py``) and drops it; this slice carries it on ``csv.received`` (additive
optional ``file_name``) and the worker persists it here at insert, beside ``template_id`` /
``mapping_version_id`` — informational lineage, not run state.

- **Nullable, no backfill** — every pre-Slice-51a row genuinely has no captured filename (the
  contract gained ``file_name`` in the same slice; history cannot be reconstructed). New worker
  writes populate it when the upload carried a filename, else NULL.
- **No FK, no index** — it is display metadata; nothing queries or joins bronze by it.
- **NOT run state** — ``processing_status`` is untouched; no new writer advances bronze run
  state (Slice 51a scope boundary). The worker (already bronze's sole writer) merely widens its
  existing INSERT by one column.

Idempotent for 0001-fresh-bootstrap parity (the updated
``schemas/postgres/bronze/data_ingress_events.sql`` manifest carries the full end state): the
ADD COLUMN is gated on column existence; the COMMENT is natively idempotent. Mirrors the
``0006_bronze_template_id`` additive-column precedent, with the target-safety guard the
0007..0016 migrations carry.

See: docs/slices/slice-51a-runs-read-surface.md, decisions.md D120.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-14

"""

from __future__ import annotations

import os

from alembic import op

# revision identifiers, used by Alembic.
revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

# Target-safety guard (Slice 1 §A.2 pattern, copied from 0007..0016).
_EXPECTED_DB = os.environ.get("POSTGRES_DB", "ithina_dis_db")
_CM_DB = "ithina_platform_db"

_COMMENT = (
    "The uploaded file's original name, parsed at upload (dis-ui-server) and carried on "
    "csv.received (additive file_name, D120), persisted here by the worker at insert for the "
    "Ingestion Runs surface. Display metadata only: no FK, no index, not run state. NULL on "
    "pre-Slice-51a rows (no backfill) and when the upload carried no filename."
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


def upgrade() -> None:
    _guard_target()
    # Gated on existence for fresh-bootstrap parity (the schemas/postgres manifest already carries
    # the column on a 0001-fresh database).
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'bronze'
                  AND table_name = 'data_ingress_events'
                  AND column_name = 'original_filename'
            ) THEN
                ALTER TABLE bronze.data_ingress_events ADD COLUMN original_filename VARCHAR(512) NULL;
            END IF;
        END
        $$;
        """
    )
    # Double any apostrophe for the SQL string literal (the comment contains "file's").
    op.execute(
        "COMMENT ON COLUMN bronze.data_ingress_events.original_filename IS '"
        + _COMMENT.replace("'", "''")
        + "'"
    )


def downgrade() -> None:
    _guard_target()
    op.execute("ALTER TABLE bronze.data_ingress_events DROP COLUMN IF EXISTS original_filename")
