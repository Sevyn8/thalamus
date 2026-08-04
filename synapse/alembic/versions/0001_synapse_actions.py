"""synapse.actions: the append-only action log — Synapse slice 5

Creates the ``synapse`` schema and ``synapse.actions``, the first table Synapse owns. Written
against a shape that had already run for a slice: the action types were frozen, an in-memory
implementation of the log protocol was in permanent use by the unit tests, and append-only was
already enforced by the absence of any mutating method. So this migration describes something
exercised — the opposite of canonical's signal-history table, a DDL written ahead of its writer
and still holding zero rows.

- upgrade():
  1. CREATE SCHEMA synapse. This chain is its sole creator; there is no bootstrap manifest to
     add it to, because this IS the first migration of Synapse's chain.
  2. GRANT USAGE on the schema to the two Synapse roles, plus ALTER DEFAULT PRIVILEGES so a
     future table in this schema does not arrive ungranted. Mirrors DIS's 0001 grants block and
     0016's treatment of a brand-new schema.
  3. Apply synapse/schemas/postgres/actions.sql VERBATIM — the DDL file is the source of truth
     for schema definition, exactly as it is for DIS. This migration authors only what no DDL
     file declares: the schema, the grants, and nothing else.
  4. Explicit table grants (belt over the default-privileges inheritance, as 0016 does):
     synapse_writer gets INSERT and NOTHING ELSE; synapse_reader gets SELECT.

  THE ROLES ARE NOT CREATED HERE. Terraform's google_sql_user owns them in cloud and
  dis/infra/local/postgres-init.sql owns them locally — the same split as every other role in
  this database. A migration that created roles would put credentials in a migration.

- downgrade(): DROP SCHEMA synapse CASCADE. Drops the table, its indexes, its policy and its
  trigger function. NOTE THAT THIS DESTROYS THE LOG, which is the one thing the table exists to
  prevent — the append-only trigger cannot stop a schema drop, and this downgrade is exactly the
  hole named in the DDL header's honest gap list. It exists because alembic wants a downgrade;
  running it against anything but a scratch database throws away history that cannot be
  reconstructed.

Revision ID: 0001
Revises:
Create Date: 2026-08-05

"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# This file: synapse/alembic/versions/0001_synapse_actions.py -> synapse root is parents[2].
_SYNAPSE_ROOT = Path(__file__).resolve().parents[2]
_DDL = _SYNAPSE_ROOT / "schemas" / "postgres" / "actions.sql"

SCHEMA = "synapse"

# The two roles this schema is granted to. Named rather than discovered: a migration that
# granted to whatever roles it found would silently widen access the day someone adds one.
_WRITER = "synapse_writer"
_READER = "synapse_reader"


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')

    # USAGE for both roles. Without it neither can reach a table however it is granted.
    for role in (_WRITER, _READER):
        op.execute(f'GRANT USAGE ON SCHEMA "{SCHEMA}" TO {role}')

    # Default privileges, so a FUTURE table in this schema is not silently unreachable — and,
    # just as importantly, so a future table does not silently arrive WRITABLE by the writer.
    # The writer's default is INSERT only, which is the whole append-only posture.
    op.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{SCHEMA}" GRANT INSERT ON TABLES TO {_WRITER}')
    op.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{SCHEMA}" GRANT SELECT ON TABLES TO {_READER}')

    # The DDL file, verbatim. The SQL is the source of truth; this migration is the applier.
    op.execute(_DDL.read_text(encoding="utf-8"))

    # Explicit table grants over the default-privileges inheritance (0016's belt). INSERT ONLY
    # for the writer: no UPDATE, no DELETE, no TRUNCATE, and deliberately no SELECT — the writer
    # never needs to read, ON CONFLICT DO NOTHING requires no SELECT, and RETURNING (which would)
    # is not used.
    op.execute(f"GRANT INSERT ON {SCHEMA}.actions TO {_WRITER}")
    op.execute(f"GRANT SELECT ON {SCHEMA}.actions TO {_READER}")


def downgrade() -> None:
    # DESTRUCTIVE, and the DDL header says why that is a hole rather than a feature.
    op.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
