"""synapse.action_events: the first operator write path, and the role that owns it

WHAT THIS ADDS. A table an operator causes rows in — snooze, dismiss (closed reason set) or
acknowledge an alert from the console — plus the dedicated role that may write it and nothing
else. Everything in synapse before this was produced by the orchestrator.

A THIRD ROLE, NOT synapse_writer, AND THE REASON IS ATTRIBUTION. synapse_writer is the
orchestrator's identity: INSERT on synapse.actions and no SELECT anywhere, so "the analysis
plane never reads what it wrote" is a runtime property. Lending it to the console would make
every row in the database ambiguous about which process caused it, and would hand an HTTP
surface a credential that can append to the action log. `synapse_lifecycle` holds INSERT on
ONE table and nothing else, so what the console can do is bounded by the grant rather than by
the code path — the same argument that separated reader from writer in the first place.

THE ROLE IS CREATED OUT OF BAND, like every other role here. Terraform creates the three
originals and this migration only GRANTS — a migration that created a login role would put a
password in the chain. `GRANT ... TO synapse_lifecycle` fails loudly if the role is absent,
which is the correct failure: it names exactly what the operator has not done yet.

    CREATE ROLE synapse_lifecycle WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
        PASSWORD '<from Secret Manager>';
    GRANT CONNECT ON DATABASE thalamus TO synapse_lifecycle;

NOBYPASSRLS IS NOT DECORATION. The table is FORCE ROW LEVEL SECURITY and its WITH CHECK pins
every insert to the session's tenant, so a bypassing role would let the console write an event
against a tenant it was not acting for.

THE DDL FILE IS THE SOURCE OF TRUTH and this applies it verbatim, matching 0001. The table's
own reasoning — append-only, closed vocabularies, why the target grain is on the event — lives
in schemas/postgres/action_events.sql rather than being restated here.

APPLY VEHICLE is the migrate-synapse Cloud Run job. It MUST run before the BFF revision that
holds the lifecycle DSN deploys: that image writes this table on its first POST.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-08

"""

from __future__ import annotations

from pathlib import Path

from alembic import op

# revision identifiers, used by Alembic.
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

SCHEMA = "synapse"
_DDL = Path(__file__).resolve().parents[2] / "schemas" / "postgres" / "action_events.sql"

# Named rather than discovered: a migration that granted to whatever roles it found would
# silently widen access the day somebody adds one.
_LIFECYCLE = "synapse_lifecycle"
_READER = "synapse_reader"
_WRITER = "synapse_writer"


def upgrade() -> None:
    # The DDL file, verbatim. Idempotent throughout (IF NOT EXISTS / DROP-then-CREATE for the
    # trigger and policy), so a fresh database that already built the table from this file at
    # bootstrap reaches this revision and finds nothing to do.
    op.execute(_DDL.read_text(encoding="utf-8"))

    op.execute(f'GRANT USAGE ON SCHEMA "{SCHEMA}" TO {_LIFECYCLE}')

    # INSERT ONLY, and deliberately no SELECT. The console reads this table through
    # synapse_reader; the writing credential cannot read back what it wrote, cannot UPDATE
    # (the trigger refuses anyway, but the grant refuses first and more cheaply) and cannot
    # DELETE. The whole console write surface is this one privilege.
    op.execute(f"GRANT INSERT ON {SCHEMA}.action_events TO {_LIFECYCLE}")

    # The read side. State derivation runs under the reader like every other console query.
    op.execute(f"GRANT SELECT ON {SCHEMA}.action_events TO {_READER}")

    # ==========================================================================================
    # REVOKE THE ORCHESTRATOR'S INHERITED INSERT. Found by RUNNING this migration, not by reading
    # it: 0001 set `ALTER DEFAULT PRIVILEGES IN SCHEMA synapse GRANT INSERT ON TABLES TO
    # synapse_writer` so that a future table would not arrive silently unreachable — and the
    # consequence is that synapse.action_events arrived INSERT-able by the orchestrator's
    # identity. A first run showed grants of INSERT:synapse_writer alongside INSERT:synapse_lifecycle.
    #
    # That defeats the reason this slice took a third role at all. If synapse_writer can append
    # lifecycle events, every row is ambiguous about whether a human or the 04:00 sweep caused it,
    # and the attribution boundary is a naming convention rather than a privilege.
    #
    # Revoked for THIS table specifically rather than by changing 0001's default: the default is
    # right for analysis tables, which the writer does own, and rewriting an applied migration to
    # fix a later one is how a chain stops describing what ran.
    op.execute(f"REVOKE ALL ON {SCHEMA}.action_events FROM {_WRITER}")


def downgrade() -> None:
    # Drops the operator's decision log. Reversible in schema, not in data: nothing else records
    # that somebody dismissed an alert as seasonal, and the training labels are gone with it.
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.action_events")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.action_events_append_only()")
