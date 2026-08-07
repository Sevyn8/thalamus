"""synapse.quarantined_tenants + actions_analytical: make the immortal fixtures invisible

WHAT THIS CLOSES. Thirteen rows in staging's synapse.actions are fixtures written by live tests
before the suite was isolated. The append-only trigger binds every role including the owner, so
deletion is not an option that exists; growth is already stopped. What remained was that a future
weight-fitting job would scan the table and train on fiction silently. This gives analytics a
surface that excludes them.

The mechanism's reasoning — why a registry rather than a predicate, why actions only, why the
registry is deliberately NOT append-only — lives in schemas/postgres/quarantined_tenants.sql,
which this applies verbatim. It is not restated here.

============================================================================================
THE SEEDED ID: WHICH decafbad, AND HOW IT WAS SETTLED
============================================================================================
The pre-flight found a one-character disagreement. A Studio read reported the thirteen rows
under ``decafbad-0000-4000-8000-000000000000``; every literal in this repository says
``...0001``. That difference decides whether the view quarantines anything at all, and the
failure is SILENT — a wrong id yields a view that excludes nothing and looks correct.

Settled on the evidence available without a database:

  - ``git log -S`` across ALL refs finds ``...000000000000`` nowhere in the repository's
    history. It has never been written down.
  - The ``...0001`` default landed in c061545 on 2026-08-04, the same day the first probe row
    was recorded (2026-08-04T16:31), and has not changed since.
  - conftest.py:448 reads that default through ``os.environ.get("SYNAPSE_PROBE_TENANT_ID")``,
    so an operator COULD have overridden it — which is the one way ...0000 could be real
    without appearing in any file.

So ``...0001`` is the best-evidenced value and is what this seeds. THE POST-APPLY CHECK IS NOT
OPTIONAL: after executing this, ``SELECT count(*) FROM synapse.actions_analytical`` must return
3, not 16. If it returns 16 the seed is wrong, and the fix is one INSERT into the registry —
which is precisely why that table is correctable while synapse.actions is not.

============================================================================================
NO 0006-CLASS ORDERING HAZARD
============================================================================================
0006 needed a role that did not exist yet, so its GRANT could fail on an operator's ordering.
This one grants only to ``synapse_reader``, which has existed since 0001 and is already granted
on synapse.actions. Nothing here requires an out-of-band step before the execute.

The ORCHESTRATOR IS EXPLICITLY DENIED, and that is the 0006 lesson rather than an ordering one:
0001's ``ALTER DEFAULT PRIVILEGES ... GRANT INSERT ON TABLES TO synapse_writer`` silently handed
the writer INSERT on the next table created in this schema. The executed test asserts the
resulting grant set rather than trusting that a view is exempt.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-08

"""

from __future__ import annotations

from pathlib import Path

from alembic import op

# revision identifiers, used by Alembic.
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

SCHEMA = "synapse"
_DDL = Path(__file__).resolve().parents[2] / "schemas" / "postgres" / "quarantined_tenants.sql"

_READER = "synapse_reader"
_WRITER = "synapse_writer"
_LIFECYCLE = "synapse_lifecycle"

# The sentinel. See the header for how this value was settled and what to check after applying.
_PROBE_TENANT = "decafbad-0000-4000-8000-000000000001"

# SEEDED IN THE MIGRATION rather than by hand, because the row's existence is exactly as old as
# the mechanism: there is no moment at which the table should exist without this entry. A
# hand-seeded registry is also a registry that arrives empty on a fresh database, which would
# make a fresh environment silently disagree with staging about what is real.
_NOTE = (
    "Test-fixture tenant. Thirteen rows in synapse.actions were written by live integration "
    "tests between 2026-08-04T16:31 and 2026-08-05T06:36 (SKU prefixes PROBE-, SKU-IDEMPO, "
    "SKU-BASELIN) before the suite gained its disposable-database isolation. They are immortal: "
    "synapse.actions is append-only by a trigger that binds the owner, so deletion is impossible "
    "by design and exclusion is the only remedy. "
    "WHAT IS STILL REAL ABOUT THIS TENANT: it is genuinely provisioned and the orchestrator runs "
    "for it. Its synapse.run rows and its freshness WARNINGs are real behaviour -- they are what "
    "verified slice 9's alert emission -- and are deliberately NOT quarantined. Only its actions "
    "are fiction. Revisit that boundary consciously if run data ever becomes a model input."
)


def upgrade() -> None:
    # The DDL file, verbatim. Idempotent throughout, so a fresh database that already built the
    # objects at bootstrap reaches this revision and finds nothing to do.
    op.execute(_DDL.read_text(encoding="utf-8"))

    # BOUND PARAMETERS, NOT AN INTERPOLATED LITERAL, and 0005 is why. That revision died on its
    # own COMMENT because the text contained an apostrophe inside a single-quoted SQL string; the
    # fix there was to double the quotes in code. This note says "slice 9's alert emission" and
    # would have died the same way -- it did, on the first execution of this migration. Binding
    # removes the entire class rather than escaping one instance of it.
    op.get_bind().exec_driver_sql(
        f"""
        INSERT INTO {SCHEMA}.quarantined_tenants
            (tenant_id, reason, note, registered_at, registered_by)
        VALUES (CAST(%s AS uuid), %s, %s, CAST(%s AS timestamptz), %s)
        ON CONFLICT (tenant_id) DO NOTHING
        """,
        (_PROBE_TENANT, "test_fixture", _NOTE, "2026-08-07 00:00:00+00", "migration 0007"),
    )

    # READ-ONLY, to the one role that reads. The console queries the base table for operations
    # and this view is for analytics; both go through synapse_reader.
    op.execute(f"GRANT SELECT ON {SCHEMA}.quarantined_tenants TO {_READER}")
    op.execute(f"GRANT SELECT ON {SCHEMA}.actions_analytical  TO {_READER}")

    # NOBODY ELSE, AND THE WRITER EXPLICITLY. See the header: 0001's default privileges are why
    # this is a statement rather than an assumption.
    op.execute(f"REVOKE ALL ON {SCHEMA}.quarantined_tenants FROM {_WRITER}, {_LIFECYCLE}")
    op.execute(f"REVOKE ALL ON {SCHEMA}.actions_analytical  FROM {_WRITER}, {_LIFECYCLE}")


def downgrade() -> None:
    # Drops the exclusion surface and the provenance with it. The thirteen rows are unaffected —
    # they were never touched and could not be.
    op.execute(f"DROP VIEW IF EXISTS {SCHEMA}.actions_analytical")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.quarantined_tenants")
