"""retire the ROOS narrative from deployed column/table comments

Comment-only migration: rewrites the three ``COMMENT ON`` texts in the DIS schema that name
"ROOS agents" as a reader of canonical data. ROOS has been retired as a module (Customer Master
migration ``0fdfbc8871a8`` removes it from ``module_code_enum`` and deletes every row that
referenced it), so deployed database metadata describing it as a current or future consumer is
a claim about a product that no longer exists.

NO column, type, nullability, constraint, index, partition, role, trigger, or policy is touched.
No data moves. A catalog metadata update takes no meaningful lock.

The three objects, each verified present in the resident DIS database before this was written:

  * ``canonical.store_sku_current_position``                        (table comment)
  * ``canonical.store_sku_current_position.yesterday_retail_price`` (column comment)
  * ``staging.store_sku_current_position.yesterday_retail_price``   (column comment)

WHY A MIGRATION FOR PROSE. Comments are deployed database state. Editing only the
``schemas/postgres`` DDL would fix the fresh-bootstrap path — 0001 applies those files verbatim
— and leave every already-migrated database carrying the old text, which is exactly the
fresh != migrated divergence the 0005 and 0015 comment reconciliations exist to prevent. The
upgrade sets text unconditionally, so it is a no-op on the fresh path and a replacement on the
delta path, and both converge.

The replacement text keeps every factual claim and drops only the retired product name:
"Read by ROOS agents and dis-ui-server" becomes "Read by dis-ui-server and downstream analytics
consumers", and "change-detection by ROOS agents" becomes "downstream change-detection". The
"yesterday" clock semantics are still TBD and still say so.

``dis_validation.provenance`` quotes the ``yesterday_retail_price`` comment verbatim to justify
classifying that column compute-owned. That quotation is updated in the same commit; a citation
of a comment that no longer reads that way is a worse artifact than the comment was.

dbt/BigQuery (the 4th step of the dis-canonical coordinated-change contract) is a NO-OP: there
is no BigQuery mirror for ``store_sku_current_position``.

Reversible, per the comment-migration convention (``0005``, ``0015``): ``downgrade()`` restores
the previous text verbatim. Nothing is lost by going back — the prior strings are right here.

Fresh == migrated is proven by ``tests/integration/test_migration_0020.py``, which also asserts
migration constant == schema-file text, the drift a comment-only migration actually risks.

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-11

"""

from __future__ import annotations

import os

from alembic import op

# revision identifiers, used by Alembic.
revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

# Target-safety guard (Slice 1 §A.2 pattern, copied from 0001..0019).
_EXPECTED_DB = os.environ.get("POSTGRES_DB", "ithina_dis_db")
_CM_DB = "ithina_platform_db"

_TABLE = "canonical.store_sku_current_position"
_CANONICAL_COLUMN = "canonical.store_sku_current_position.yesterday_retail_price"
_STAGING_COLUMN = "staging.store_sku_current_position.yesterday_retail_price"

# The texts, verbatim. Each NEW string MUST match its schemas/postgres DDL file exactly or the
# fresh==migrated convergence test fails.
_NEW_TABLE_COMMENT = (
    "System of record for current SKU instance state at every store. One row per (tenant, "
    "store, sku, variant, lot). Written by the streaming consumer via LWW upserts keyed on "
    "source_event_timestamp. Read by dis-ui-server and downstream analytics consumers. "
    "Carries denormalized catalogue and store context for read ergonomics. Tenant-isolated "
    "via RLS."
)
_OLD_TABLE_COMMENT = (
    "System of record for current SKU instance state at every store. One row per (tenant, "
    "store, sku, variant, lot). Written by the streaming consumer via LWW upserts keyed on "
    "source_event_timestamp. Read by ROOS agents and dis-ui-server. Carries denormalized "
    "catalogue and store context for read ergonomics. Tenant-isolated via RLS."
)

# canonical and staging carry byte-identical text for this column; one pair of constants drives
# both statements so they cannot drift apart here.
_NEW_COLUMN_COMMENT = (
    "Previous-day retail price for downstream change-detection. Clock semantics for "
    '"yesterday" (tenant local / store local / UTC) TBD.'
)
_OLD_COLUMN_COMMENT = (
    "Previous-day retail price for change-detection by ROOS agents. Clock semantics for "
    '"yesterday" (tenant local / store local / UTC) TBD.'
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


def _comment_sql(kind: str, target: str, comment: str) -> str:
    """One ``COMMENT ON`` statement; single quotes doubled for the SQL literal.

    COMMENT ON does not accept bind parameters, so the text is inlined.
    """
    escaped = comment.replace("'", "''")
    return f"COMMENT ON {kind} {target} IS '{escaped}'"


def _apply(table_comment: str, column_comment: str) -> None:
    _guard_target()
    bind = op.get_bind()
    bind.exec_driver_sql(_comment_sql("TABLE", _TABLE, table_comment))
    bind.exec_driver_sql(_comment_sql("COLUMN", _CANONICAL_COLUMN, column_comment))
    bind.exec_driver_sql(_comment_sql("COLUMN", _STAGING_COLUMN, column_comment))


def upgrade() -> None:
    _apply(_NEW_TABLE_COMMENT, _NEW_COLUMN_COMMENT)


def downgrade() -> None:
    _apply(_OLD_TABLE_COMMENT, _OLD_COLUMN_COMMENT)
