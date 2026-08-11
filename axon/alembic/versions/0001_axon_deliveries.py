"""axon.platform_deliveries + axon.tenant_deliveries: the delivery ledger

Axon slice 1. This chain's first revision, and it does four things:

  1. CREATE SCHEMA axon. This chain is its sole creator; there is no bootstrap manifest to
     add it to. The DDL file carries the statement so a hand-run of the file alone also
     works, and it is IF NOT EXISTS so re-running is a no-op.
  2. Apply schemas/postgres/deliveries.sql VERBATIM. The file is the source of truth for
     schema definition; a migration that retyped it would be a second copy free to disagree.
     Same helper shape and same reason as Synapse's 0001 and 0003.
  3. GRANT USAGE on the schema to axon_sender.
  4. GRANT INSERT on axon.platform_deliveries to axon_sender, and NOTHING else to anybody.

WHAT IS DELIBERATELY NOT GRANTED, and each absence is the point:

  - NO SELECT, on either table, to any role. The send path performs ZERO database reads:
    the on-call address is configuration, the credential is an env-mounted secret, the id
    is minted by the caller, and the write is one INSERT with no RETURNING and no ON
    CONFLICT. A role that cannot read cannot be made to leak a ledger.
  - NOTHING AT ALL on axon.tenant_deliveries. It ships empty in this slice. Its grant
    arrives with the first tenant send, together with the tenant-scoped session that
    policy's WITH CHECK forces.
  - NO ALTER DEFAULT PRIVILEGES. Synapse's 0001 set them and its own later migrations had
    to re-assert REVOKEs because a default silently handed the writer INSERT on every
    FUTURE table in the schema. That is a trap this chain declines to set: a grant here is
    written per table, visibly, once.

THE ROLE MUST EXIST BEFORE THIS RUNS. axon_sender is created out of band (a login role in
git is a password in git), exactly as synapse_lifecycle and synapse_provisioner are. This
is 0006's recorded ordering hazard and it is avoided by sequence rather than by luck: the
manual prerequisites list the CREATE ROLE first.

Revision ID: 0001
Revises:
Create Date: 2026-08-10

"""

from __future__ import annotations

from pathlib import Path

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "axon"
_SCHEMAS = Path(__file__).resolve().parents[2] / "schemas" / "postgres"

_SENDER = "axon_sender"


def _apply(filename: str) -> None:
    """Apply a DDL file verbatim. Same helper shape as Synapse's 0001, same reason: the file
    is the source of truth for schema definition and a migration that retyped it would be a
    second copy free to disagree."""
    op.execute((_SCHEMAS / filename).read_text(encoding="utf-8"))


def upgrade() -> None:
    # The DDL file opens with CREATE SCHEMA IF NOT EXISTS axon, so the schema and both
    # tables arrive together and a hand-run of the file alone behaves identically.
    _apply("deliveries.sql")

    op.execute(f'GRANT USAGE ON SCHEMA "{SCHEMA}" TO {_SENDER}')

    # ONE VERB, ONE TABLE. See the module docstring for every absence.
    op.execute(f"GRANT INSERT ON {SCHEMA}.platform_deliveries TO {_SENDER}")


def downgrade() -> None:
    # Drops the ledger and everything in it. There is no recovering a delivery record from
    # anywhere else: the provider knows what it accepted, not what we asked it to accept or
    # why, and a suppressed row was never sent at all so no provider ever saw it.
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.tenant_deliveries")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.platform_deliveries")
    op.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}"')
