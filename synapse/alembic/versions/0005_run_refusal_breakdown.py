"""synapse.run: the refusal breakdown, so two different zeroes stop looking alike

WHAT THIS CLOSES. ``actions_proposed = 0`` has meant either "the analysis looked and found
nothing" or "the analysis could not assess anything" — most often because every series was
refused as stale, which is the dominant real case on this data. Nothing in the row told them
apart, so the console shipped a third rendering state meaning "zero, and we cannot tell which",
and a row on the tenant page describing this very gap was deleted in Phase A rather than left
lying about what it knew. This column is what removes the ambiguity at the source.

ADDITIVE AND NULLABLE, so it applies to a live table with rows already in it and no backfill is
possible or attempted: the findings behind past runs were never persisted, so an older run's
breakdown is genuinely unknown rather than empty. That is precisely what NULL says here.

NULL AND '{}' ARE DIFFERENT FACTS, and the code depends on it:

    NULL  the run never reached its plan — blocked, undeclared, failed, or it predates this
          migration. Nothing was assessable, and the outcome column already says why.
    '{}'  the plan RAN and refused nothing. Every position was assessable.

Collapsing them with COALESCE would report a crashed run as a clean one.

JSONB RATHER THAN TYPED COLUMNS OR A CHILD TABLE. Five columns would make every new refusal
branch a migration, and the vocabulary grows with the analyses. A child table would be right if
this were aggregated across runs; it is read only alongside its own run row.

NO CHECK ON THE KEYS, deliberately. A constraint enumerating RefusalReason's members would put
the vocabulary in two places and make adding a branch a migration — the thing JSONB was chosen to
avoid. The closed set is enforced where it is produced (``_refusal`` returns the enum) and
asserted in the unit suite, which is the layer that can name a violation usefully.

IDEMPOTENT, matching 0004 and the 0002/0003 precedent: ``ADD COLUMN IF NOT EXISTS``, so a fresh
database bootstrapped from the updated ``schemas/postgres/run.sql`` reaches this revision and
finds nothing to do.

APPLY VEHICLE is the ``migrate-synapse`` Cloud Run job, proven 2026-08-06. It MUST run before any
image that binds this column deploys — the orchestrator writes it and the BFF selects it, and
both fail against a database without it. That ordering is the slice-10 lesson.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-07

"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_COMMENT = (
    "What the analysis could not assess, as {reason: count} over the closed vocabulary in "
    "synapse.core.stockout_risk.RefusalReason. NULL means the run never reached its plan "
    "(blocked/undeclared/failed, or it predates migration 0005); '{}' means the plan ran and "
    "refused nothing -- collapsing the two would report a crashed run as a clean one. Keys are "
    "written sorted so a re-run of the same slot over the same data stores identical bytes."
)


def upgrade() -> None:
    op.execute("ALTER TABLE synapse.run ADD COLUMN IF NOT EXISTS refusals JSONB")
    op.execute(f"COMMENT ON COLUMN synapse.run.refusals IS '{_COMMENT}'")


def downgrade() -> None:
    # Loses breakdowns that cannot be recomputed: the findings behind them were never persisted,
    # exactly as 0004's observations were not. Reversible in schema, not in data.
    op.execute("ALTER TABLE synapse.run DROP COLUMN IF EXISTS refusals")
