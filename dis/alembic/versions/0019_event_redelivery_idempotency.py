"""canonical event tables: row_hash + the redelivery-idempotency unique index

THE BUG THIS CLOSES, observed live 2026-07-31 on the first sales data the platform
has ever held: one 328-row upload became 1640 rows with nobody touching it. A chunk
failed a CHECK, nacked, and retried under the Pub/Sub retry policy; once the template
was corrected each retry SUCCEEDED, and each success appended a COMPLETE duplicate
set. Bounded only by max_delivery_attempts (100).

So this is not "an operator might re-upload". THE RETRY MECHANISM ITSELF DUPLICATES:
any transient failure on the event path — a DB blip, a timeout — produces a duplicate
the moment it succeeds. The retry policy is CORRECT (it is what bounds the
poison-message loop) and is deliberately NOT weakened here. The sink was what was
wrong.

WHY THIS DOES NOT REPEAL D33 / hard rule 7. D33 keeps the event tables append-only so
that corrections arrive as separate rows and latest-wins resolves them at read time.
That design distinguishes a CORRECTION from a REDELIVERY; it just never enforced the
distinction, so redeliveries accumulated as if they were corrections. The unique index
added here constrains the dedup key PLUS ``row_hash`` — a byte-identical repeat of the
payload. A correction differs in payload, so it differs in hash, so it is NOT blocked
and still lands as its own row. The append-only posture survives for the case it was
designed for; only the meaningless repeat is refused.

Adds to BOTH event tables (D4 — one sink, one failure mode; fixing one and leaving the
other is how the poll-loop swallow bled twice):

- ``row_hash VARCHAR(64) COLLATE "C" NOT NULL`` — sha256 hex (always 64 chars) of the
  mapping-produced payload, computed by the consumer's ``canonical_row_hash``.
  Collation "C" matches ``source_id``/``source_event_id`` so all five index columns
  compare byte-wise.
- ``uq_{ssse,ssce}_redelivery`` UNIQUE (tenant_id, store_id, source_id,
  source_event_id, row_hash).

Change events are MORE exposed than sale events, not less: they carry no native source
event id, so every row keys on the D65 ``bronze_ref:chunk_row_index`` fallback.

SCOPE IS CANONICAL ONLY, matching 0003's own precedent: the staging mirrors never
received 0003's ``source_id``/``source_event_id`` columns (verified — their
``ingest_metadata`` comment still lists source_event_id as a JSONB key), and nothing in
the codebase writes ``staging.store_sku_*``. Adding a NOT NULL column keyed on a
dedup key those tables do not have would be inventing a shape.

NOT NULL with no DEFAULT is legal only against an empty table. Both canonical event
tables are at 0 rows (the duplicated data was purged before this was written), which is
the cheapest this migration will ever be. Emptiness is re-checked HERE, immediately
before each ADD, and only when the column is genuinely about to be added — because 0001
applies the ``schemas/postgres`` DDL files dynamically, a fresh database bootstraps
these from the updated manifest and this migration must then be a no-op (the 0002/0003
idempotency pattern).

A pipeline-level ``processed_chunks`` ledger keyed (tenant, bronze_ref, chunk_index) is
the better long-term shape and is deliberately NOT built here: it would make each
table's own key irrelevant and it collides with ``ingress.resubmit`` (Slice 12), where
a replay must be able to re-land deliberately. Recorded on the ledger, not deferred
silently.

See: decisions.md D33/D38/D65 (and the D33 revision this implies), hard rule 7.

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-31

"""

from __future__ import annotations

import os

from alembic import op

# revision identifiers, used by Alembic.
revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

# Target-safety guard (Slice 1 §A.2 pattern, copied from 0001/0002/0003). Expected
# DIS database name, with the Customer Master database hard-blocked regardless.
_EXPECTED_DB = os.environ.get("POSTGRES_DB", "ithina_dis_db")
_CM_DB = "ithina_platform_db"

# (qualified table, unique index name). Canonical only — see the module docstring.
_EVENT_TABLES = (
    ("canonical.store_sku_sale_events", "uq_ssse_redelivery"),
    ("canonical.store_sku_change_events", "uq_ssce_redelivery"),
)

_ROW_HASH_DDL = 'row_hash VARCHAR(64) COLLATE "C"'

_ROW_HASH_COMMENT = (
    "sha256 hex of the mapping-produced payload (orjson, sorted keys; the consumer''s "
    "canonical_row_hash). Fifth component of the redelivery unique index, which is what "
    "lets uniqueness coexist with D33: a redelivery reproduces the payload exactly so its "
    "hash collides and the insert is suppressed, while a correction differs in payload, "
    "differs in hash, and still lands as its own row. Covers the mapping-produced columns "
    "only — tax_treatment and mapping_version_id are outside it. Consumer-injected "
    "(migration 0019)."
)


def check_migration_target(current: str, *, expected_db: str = _EXPECTED_DB, cm_db: str = _CM_DB) -> None:
    """Pure target check: refuse Customer Master outright, require the DIS database.

    Split from the connection read so the refusal logic is unit-testable without a live
    bind (the non-skippable anchor for the target-safety criterion). Identical contract
    to 0003's — deliberately duplicated rather than imported, so a migration never
    depends on a sibling revision's module staying put.
    """
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
    """Refuse to run against the wrong database. Protects both local (two Postgres
    instances: DIS on 5433, Customer Master on 5432) and cloud."""
    current = op.get_bind().exec_driver_sql("SELECT current_database()").scalar()
    check_migration_target(str(current))


def _column_exists(qualified_table: str, column: str) -> bool:
    schema, table = qualified_table.split(".", 1)
    row = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s AND column_name = %s",
            (schema, table, column),
        )
        .scalar()
    )
    return row is not None


def _assert_empty(qualified_table: str, column: str) -> None:
    """The NOT NULL ADD (no DEFAULT) is legal only against an empty table.

    Re-checked immediately before the add (plan-time row counts can stale); a non-empty
    table here means the precondition broke — abort loudly, and the single migration
    transaction rolls everything back. If this fires, the correct response is to decide
    what the existing rows' row_hash should be, NOT to add the column with a placeholder
    default: a placeholder would make every pre-existing row collide with every other,
    and the unique index would then reject legitimate history.
    """
    count = op.get_bind().exec_driver_sql(f"SELECT COUNT(*) FROM {qualified_table}").scalar()
    if count != 0:
        raise RuntimeError(
            f"Refusing to ADD {column} NOT NULL: {qualified_table} has {count} rows "
            f"(expected 0). Backfilling row_hash requires re-deriving each row's "
            f"mapping-produced payload hash; do that deliberately, then re-run."
        )


def upgrade() -> None:
    _guard_target()

    for table, index_name in _EVENT_TABLES:
        if not _column_exists(table, "row_hash"):
            _assert_empty(table, "row_hash")
            op.get_bind().exec_driver_sql(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {_ROW_HASH_DDL} NOT NULL"
            )
        op.get_bind().exec_driver_sql(f"COMMENT ON COLUMN {table}.row_hash IS '{_ROW_HASH_COMMENT}'")
        # The one uniqueness constraint on these tables. Plain (non-partitioned) since
        # 0009, so no partition key is required in the index — a UNIQUE index on a
        # partitioned parent would have had to carry event_date.
        op.get_bind().exec_driver_sql(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {table} "
            "(tenant_id, store_id, source_id, source_event_id, row_hash)"
        )


def downgrade() -> None:
    _guard_target()
    for table, index_name in _EVENT_TABLES:
        op.get_bind().exec_driver_sql(f"DROP INDEX IF EXISTS canonical.{index_name}")
        op.get_bind().exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN IF EXISTS row_hash")
