"""bronze.data_ingress_events: keyset-pagination covering index (Slice 51b)

The single additive DDL of Slice 51b (D124): a composite index
``(tenant_id, received_at DESC, id DESC)`` so the Ingestion Runs keyset predicate — the
ROW-VALUE comparison ``(received_at, id) < (:r, :i)`` over the 51a ``received_at DESC, id DESC``
ordering — seeks directly into the index instead of scanning-and-filtering from the newest row.

Proven by live EXPLAIN (ANALYZE, BUFFERS), 50k rows, worst-case boundary inside a 2,000-row
same-second cluster: with this index the boundary is a full Index Cond, an Index-Only Scan,
ZERO rows removed by filter (0.08 ms, constant with page depth); without it the same-second
cluster is filtered (heap-fetching, ~1k rows removed per page). The OR-expanded predicate form
is never index-pushed (offset-like scan) and is FORBIDDEN in the repo (a regression test guards
this) — this index is only useful together with the row-value form.

- **Index only** — no column, no data, no constraint; the worker remains bronze's sole DATA
  writer (D111). Additive: nothing existing depends on its absence.
- **No CONCURRENTLY** — Alembic runs DDL in a transaction (where CREATE INDEX CONCURRENTLY is
  illegal) and there is no CONCURRENTLY precedent in this migration set; at beta bronze volume
  the brief write-lock is negligible. If bronze is large when this reaches cloud, switch to a
  non-transactional CONCURRENTLY build.

Idempotent for 0001-fresh-bootstrap parity (fresh == migrated): the updated
``schemas/postgres/bronze/data_ingress_events.sql`` manifest already carries this index on a
0001-fresh database, so the ``CREATE INDEX IF NOT EXISTS`` here no-ops on fresh and creates it
on an already-migrated (pre-0018) database. Mirrors the existence-gate 0017 uses for its ADD
COLUMN, with the target-safety guard the 0007..0017 migrations carry.

See: docs/slices/slice-51b-runs-pagination.md, decisions.md D124.

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-14

"""

from __future__ import annotations

import os

from alembic import op

# revision identifiers, used by Alembic.
revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

# Target-safety guard (Slice 1 §A.2 pattern, copied from 0007..0017).
_EXPECTED_DB = os.environ.get("POSTGRES_DB", "ithina_dis_db")
_CM_DB = "ithina_platform_db"

_INDEX = "ix_bdie_tenant_received_at_id"


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
    # Existence-gated for fresh-bootstrap parity (the manifest already carries the index on a
    # 0001-fresh database). IF NOT EXISTS is the index-level equivalent of 0017's column gate.
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {_INDEX} "
        "ON bronze.data_ingress_events (tenant_id, received_at DESC, id DESC)"
    )


def downgrade() -> None:
    _guard_target()
    op.execute(f"DROP INDEX IF EXISTS bronze.{_INDEX}")
