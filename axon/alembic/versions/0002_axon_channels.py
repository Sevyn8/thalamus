"""axon.channel_connections + axon.channel_templates, and the ledger's composite FK

Axon slice 4: the tenant channel rails. Three things, in one revision because the third
cannot exist without the second:

  1. axon.channel_connections. Per tenant per channel: provider, status, sending identity,
     and the NAME of the Secret Manager secret holding the credential. Never the credential.
  2. axon.channel_templates. Per tenant per channel per notification class: which approved
     provider template name renders it, under config.source_mappings' lifecycle.
  3. The composite FOREIGN KEY on axon.tenant_deliveries (tenant_id, template_version_id).

THE ORDERING BITES AND IT IS INSIDE ONE FILE. The foreign key can only reference a
UNIQUE (tenant_id, template_version_id), and that constraint is declared inline on
channel_templates, so it exists at CREATE TABLE time and the ALTER at the foot of the DDL
cannot outrun it. Splitting the two across revisions would create a window in which the
chain is at a head that has a table and no key, which is a state nothing needs.

WHY THE FOREIGN KEY IS TWO COLUMNS, AND THIS IS A MEASUREMENT.
Both forms were built in a scratch schema against a real Postgres, both tables FORCE ROW
LEVEL SECURITY under axon.tenant_deliveries' exact policy, written to by a NOSUPERUSER
NOBYPASSRLS role holding INSERT and no SELECT:

  - SINGLE COLUMN: a tenant-A delivery, written in a session whose app.tenant_id was
    tenant A, successfully pinned a tenant-B template version. The INSERT was ACCEPTED,
    because referential-integrity checks bypass row level security. The policy that stops a
    session READING another tenant's template does not stop it POINTING at one.
  - COMPOSITE: the same cross-tenant insert was REJECTED with a foreign key violation, and
    the same-tenant insert and a NULL both remained accepted.

The single-column form would look like a guard while permitting the exact cross-tenant
write that tenant_deliveries' WITH CHECK asymmetry exists to refuse. That is the reason,
rather than a general claim that composite keys are safer.

The probe also confirmed the writing role needed NO SELECT on the referenced table, so this
constraint forces no read privilege onto axon_sender.

NOTHING IN THIS REVISION HAS EVER EXECUTED BEFORE THIS JOB RUNS.
Axon's suite is offline by design, neither local container carries an axon schema, and
every constraint and policy here is text-checked by tests/test_channels_ddl.py and first
executed by migrate-axon against staging. The one exception is the foreign key's
cross-tenant behaviour above, which was executed for real before the DDL was written.

NO GRANTS, AND THAT IS SLICE 1'S RECORDED PRECEDENT RATHER THAN AN OVERSIGHT.
Both tables ship EMPTY and UNGRANTED, exactly as axon.tenant_deliveries did. Nothing reads
them: there is no console surface. Nothing writes them: there is no form and no adapter.
06_axon_sender_grant.sql states the rule this follows, that a grant arrives with the code
that needs it and together with the session posture that code must open. Granting SELECT to
axon_reader now would create a credential reaching tables no code opens a session against.

THE EXTENSION IS A HARD DEPENDENCY, NOT A CONVENIENCE. channel_templates carries a gist
EXCLUDE and the DDL file opens with CREATE EXTENSION IF NOT EXISTS btree_gist. If the role
running this chain cannot create it, that statement raises and the whole revision rolls
back, which is the behaviour wanted: the alternative is a table created without its label
guard and nothing saying so. Axon's chain runs as postgres in staging, which can.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-14

"""

from __future__ import annotations

from pathlib import Path

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SCHEMA = "axon"
_SCHEMAS = Path(__file__).resolve().parents[2] / "schemas" / "postgres"


def _apply(filename: str) -> None:
    """Apply a DDL file verbatim. Same helper and same reason as 0001: the file is the
    source of truth for schema definition and a migration that retyped it would be a second
    copy free to disagree."""
    op.execute((_SCHEMAS / filename).read_text(encoding="utf-8"))


def upgrade() -> None:
    # Both tables, both policies, the trigger and the composite foreign key. The file is
    # internally ordered so the FK's target exists before the ALTER that references it, and
    # it is idempotent throughout, so a hand-run behaves identically.
    _apply("channels.sql")


def downgrade() -> None:
    # THE FOREIGN KEY COMES OFF FIRST. Dropping channel_templates while tenant_deliveries
    # still references it would fail, and the failure would be correct: the constraint is
    # what makes the reference meaningful.
    op.execute(
        f"ALTER TABLE {SCHEMA}.tenant_deliveries DROP CONSTRAINT IF EXISTS fk_tenant_deliveries_template"
    )
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.channel_templates")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.set_channel_template_version_seq()")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.channel_connections")
    # btree_gist is NOT dropped. It is a database-level object that config.source_mappings
    # also depends on, and dropping it here would break a table in another schema that this
    # revision never created.
