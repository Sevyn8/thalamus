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

NOT NULL DEFAULT '{}', SO THERE IS EXACTLY ONE SHAPE TO READ. An earlier draft of this migration
made the column nullable and gave NULL its own meaning ("the run never reached its plan"). That
was a THIRD state nothing produced: the orchestrator initialises the breakdown to an empty map and
writes it on every path, so a blocked or failed run stored '{}' regardless — the DDL comment
described a distinction the writer never made. Two sources of truth about one column, and the
prose was the wrong one.

So the meaning is now single and honest:

    '{}'   no refusals were recorded for this run.
    '{..}' counts by reason.

"Why did this run assess nothing" is answered by ``outcome`` — blocked, undeclared, failed — which
already carries it and does not need a second, weaker encoding here. A pre-0005 row backfills to
'{}' and reads as "no refusals recorded", which is exactly true of it.

THE DEFAULT MAKES THE BACKFILL ATOMIC AND CHEAP. Postgres 11+ stores a non-volatile column default
in the catalogue rather than rewriting every row, so this is metadata-only on a populated table.

JSONB RATHER THAN TYPED COLUMNS OR A CHILD TABLE. Five columns would make every new refusal
branch a migration, and the vocabulary grows with the analyses. A child table would be right if
this were aggregated across runs; it is read only alongside its own run row.

NO CHECK ON THE KEYS, deliberately. A constraint enumerating RefusalReason's members would put
the vocabulary in two places and make adding a branch a migration — the thing JSONB was chosen to
avoid. The closed set is enforced where it is produced (``_refusal`` returns the enum) and
asserted in the unit suite, which is the layer that can name a violation usefully.

THE COMMENT IS ESCAPED PROGRAMMATICALLY, and that is not fussiness. The first version of this
migration interpolated a comment containing ``'{}'`` into a single-quoted SQL literal and died
with ``syntax error at or near "{"`` — after the ADD COLUMN, so the whole revision rolled back and
the stamp stayed at 0004. 0004 escapes its own comments by hand-doubling the apostrophes, which
works until someone edits the text. Doubling in code cannot be forgotten.

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
    "synapse.core.stockout_risk.RefusalReason. An empty map means no refusals were recorded for "
    "this run; why a run assessed nothing at all is answered by outcome, not here. Keys are "
    "written sorted so a re-run of the same slot over the same data stores identical bytes."
)


def _quoted(comment: str) -> str:
    """SQL string literal with apostrophes doubled. See the header: the unescaped version of this
    comment is what made the first attempt at this revision fail."""
    escaped = comment.replace("'", "''")
    return f"'{escaped}'"


def upgrade() -> None:
    # NOT NULL with a constant DEFAULT: existing rows backfill in the catalogue rather than by a
    # table rewrite (Postgres 11+), so this is metadata-only however many runs are recorded.
    op.execute("ALTER TABLE synapse.run ADD COLUMN IF NOT EXISTS refusals JSONB NOT NULL DEFAULT '{}'::jsonb")
    op.execute(f"COMMENT ON COLUMN synapse.run.refusals IS {_quoted(_COMMENT)}")


def downgrade() -> None:
    # Loses breakdowns that cannot be recomputed: the findings behind them were never persisted,
    # exactly as 0004's observations were not. Reversible in schema, not in data.
    op.execute("ALTER TABLE synapse.run DROP COLUMN IF EXISTS refusals")
