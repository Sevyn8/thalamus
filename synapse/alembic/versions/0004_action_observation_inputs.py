"""Two nullable observation columns on synapse.actions: days_since_last_sale, days_of_cover.

WHAT THESE ARE, AND WHAT THEY ARE EMPHATICALLY NOT. They are OBSERVATIONS — the finding's own
measure at the moment the action was first recorded. They are not scores, not weights, not a
rank, and nothing reads them yet. Slice 10 deliberately built no scorer: ranking is comparative
and there is exactly ONE action in the log, so any weight fitted today would be fitted to n=1.
What ranking will need when it is scoped is a HISTORY, and a history cannot be backfilled — the
values were being computed inside the sweep and discarded every day. These columns stop the
discarding; they decide nothing.

ONE PER ANALYSIS, THE OTHER STAYS NULL. dead_stock measures days since the last sale;
stockout_risk measures days of cover. Both are "urgency" in English and they are not the same
quantity, so folding them into one column would produce a field whose meaning depended on
declaration_id — comparable-looking and not comparable.

FIRST OBSERVATION, NOT LATEST, AND THIS IS A CONTRACT RATHER THAN AN ACCIDENT. Neither column is
part of ``payload_hash``'s material, which is an explicit five-key allow-list in
``action_log_postgres.payload_hash`` — ``quantity_at_stake``, ``expires_on``, ``arm``,
``capability_versions``, ``thresholds``. So a re-run of the same slot whose ONLY difference is one
of these values hashes identically, collides on ``uq_actions_idempotency``, and is suppressed:
the stored figure remains the one from the run that landed first. That is the correct behaviour —
a repeat detection is not a correction — and it is pinned by a test rather than left as a comment
(tests/unit/test_action_log.py, first-observation semantics).

ADDITIVE, NULLABLE, NO DEFAULT, NO BACKFILL. Three consequences worth stating:

  - Nullable with no default is metadata-only in PostgreSQL 11+, so no table rewrite touches the
    existing rows of an append-only log.
  - The append-only trigger is ``BEFORE UPDATE OR DELETE`` (schemas/postgres/actions.sql). DDL is
    neither, so ``ALTER TABLE ... ADD COLUMN`` does not fire it, and population happens only at
    INSERT. The trigger is untouched by this migration.
  - No backfill, because there is nothing to backfill FROM: findings are not persisted anywhere
    (synapse has three tables — actions, provision, run — and none holds a finding), so the
    inputs behind existing rows no longer exist. NULL is the honest value and the column comments
    say what it means.

GRANTS ARE UNCHANGED. Adding a column to a table the roles already hold privileges on does not
alter those privileges: synapse_writer keeps INSERT, synapse_reader keeps SELECT.
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE synapse.actions ADD COLUMN IF NOT EXISTS days_since_last_sale INTEGER NULL")
    op.execute("ALTER TABLE synapse.actions ADD COLUMN IF NOT EXISTS days_of_cover NUMERIC(14,3) NULL")

    # NUMERIC(14,3) matches StockoutRiskRow.days_of_cover's Decimal and canonical's own scale on
    # every quantity column, so a figure does not change precision on its way into the log.
    op.execute(
        """
        COMMENT ON COLUMN synapse.actions.days_since_last_sale IS
        'Observation, not a score: the dead_stock finding''s own measure at the moment the action was
first recorded. NULL means the row predates this migration, or the input was unavailable for
this analysis (stockout_risk never sets it). Outside payload_hash by construction.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN synapse.actions.days_of_cover IS
        'Observation, not a score: the stockout_risk finding''s own measure at first recording. NULL
means the row predates this migration, or the analysis does not produce it (dead_stock).'
        """
    )


def downgrade() -> None:
    # Dropping these loses observations that cannot be recomputed — the findings behind them were
    # never persisted. Reversible in schema, not in data, and the docstring above is where that
    # is argued.
    op.execute("ALTER TABLE synapse.actions DROP COLUMN IF EXISTS days_of_cover")
    op.execute("ALTER TABLE synapse.actions DROP COLUMN IF EXISTS days_since_last_sale")
