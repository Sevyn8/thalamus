"""synapse.actions: retail_value_locked, the third observation column

WHAT IT CARRIES. ``stock_qty x current_retail_price`` at the moment overstock_cash_locked
flagged the position -- the capital sitting still, stated in currency.

FROZEN AT DETECTION, which is the whole reason it is a column rather than a read-time join.
The alert detail page already joins canonical.store_sku_current_position, so the console COULD
multiply today's price by today's stock and render a number without any migration. That number
would answer a different question: it mixes the price now with a detection then, which is the
two-instants error the freshness enum exists to prevent and which 5c already had to label its
way around on the stat row. Grading and weight-fitting need the value AS IT WAS.

THIRD OF A FAMILY, not a new pattern: 0004 added days_since_last_sale and days_of_cover on the
same argument, and its header is where the frozen-at-detection semantics were first written
down.

SAFE FOR IDEMPOTENCY BY CONSTRUCTION. payload_hash covers an explicit five-key allow-list --
quantity_at_stake, expires_on, arm, capability_versions, thresholds
(persistence/action_log_postgres.py:119-127) -- so a new column cannot change any existing
row's hash and cannot make a re-run land as a correction.

NULL MEANS "NOT COMPUTED BY THIS ANALYSIS". dead_stock and stockout_risk leave it NULL and
always will; only overstock_cash_locked sets it. Rows written before this migration are NULL
for the same reason plus one more -- the analysis did not exist -- and neither case is
distinguishable from the other, deliberately: both mean "no such figure was ever produced here".

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-08

"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_COMMENT = (
    "Observation, not a score: the RETAIL value of the flagged stock at the DETECTION-TIME "
    "price (stock_qty x current_retail_price), recorded by overstock_cash_locked. Explicitly "
    "NOT cost and NOT margin -- unit_cost has no determined basis while canonical's "
    "tax_treatment is TBD, so a cost-derived money figure would be a confident wrong number "
    "(the rule stated at synapse/core/stockout_risk.py:14-17). NULL means this analysis did not "
    "produce the figure: dead_stock and stockout_risk never set it, and rows predating "
    "migration 0008 have none. Outside payload_hash by construction."
)


def _quoted(comment: str) -> str:
    """SQL string literal with apostrophes doubled -- 0005 died on an unescaped one."""
    return "'" + comment.replace("'", "''") + "'"


def upgrade() -> None:
    op.execute("ALTER TABLE synapse.actions ADD COLUMN IF NOT EXISTS retail_value_locked NUMERIC(18, 2)")
    op.execute(f"COMMENT ON COLUMN synapse.actions.retail_value_locked IS {_quoted(_COMMENT)}")

    # ==========================================================================================
    # THE ANALYTICAL VIEW MUST BE REFRESHED, AND MISSING THIS WOULD HAVE BEEN SILENT.
    # ==========================================================================================
    # 0007's synapse.actions_analytical is defined as ``SELECT a.* FROM synapse.actions a``, and
    # Postgres EXPANDS the star AT CREATION TIME into a fixed column list. So on any database
    # where 0007 ran before this migration -- staging -- the view does NOT gain
    # retail_value_locked when the table does. The surface analytics is told to read would be
    # missing the very column M1 exists to record, and nothing would raise: queries against the
    # view would simply not see it.
    #
    # A FRESH DATABASE CANNOT SHOW THIS. There, 0001 creates the table WITH the column (it is in
    # actions.sql) and 0007 builds the view over it, so the view has the column already and the
    # defect is invisible. It is only reproducible by reconstructing staging's 0007 state --
    # which is what the executed migration test does.
    #
    # CREATE OR REPLACE re-expands the star. It is legal here because the new column is appended
    # at the end: Postgres permits adding trailing columns to a view, only refusing to remove or
    # retype existing ones.
    op.execute(
        """
        CREATE OR REPLACE VIEW synapse.actions_analytical
            WITH (security_invoker = true) AS
        SELECT a.*
          FROM synapse.actions a
         WHERE NOT EXISTS (
             SELECT 1 FROM synapse.quarantined_tenants q
              WHERE q.tenant_id = a.tenant_id
         )
        """
    )


def downgrade() -> None:
    # The view depends on the column, so it goes first and is rebuilt without it.
    op.execute("DROP VIEW IF EXISTS synapse.actions_analytical")
    # Loses observations that cannot be recomputed at their detection-time price: the position's
    # price has moved on and the finding behind it was never persisted. Reversible in schema,
    # not in data -- exactly as 0004's two columns are.
    op.execute("ALTER TABLE synapse.actions DROP COLUMN IF EXISTS retail_value_locked")
    op.execute(
        """
        CREATE OR REPLACE VIEW synapse.actions_analytical
            WITH (security_invoker = true) AS
        SELECT a.* FROM synapse.actions a
         WHERE NOT EXISTS (
             SELECT 1 FROM synapse.quarantined_tenants q WHERE q.tenant_id = a.tenant_id
         )
        """
    )
