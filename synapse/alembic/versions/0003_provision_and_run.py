"""synapse.provision and synapse.run — the orchestrator's inputs and its denominator

Slice 6a. Two tables, both in the schema 0001 created, both applied VERBATIM from their DDL
files — the same discipline as 0001: the schema files are the source of truth and this
migration authors only what no DDL file declares, which here is the grants.

- ``synapse.provision`` — WHICH tenants have WHICH analyses enabled. The SELECTION half of the
  envelope/selection split; the ENVELOPE lives on ``AnalysisDeclaration.max_rung`` in code.
- ``synapse.run`` — one row per (tenant, analysis, slot). The attribution DENOMINATOR, and the
  only place a run that produced ZERO actions is visible at all.

THE GRANTS, AND ONE REAL WIDENING OF synapse_writer:

    synapse_reader   SELECT on both tables.
    synapse_writer   SELECT, INSERT and UPDATE on synapse.run — and nothing on provision.

``synapse_writer`` holding SELECT and UPDATE is a genuine departure from slice 5, where the
whole point was a writer that could not read. It is confined to ``synapse.run`` and it is
forced by the table's job: claiming a slot is INSERT ... ON CONFLICT DO NOTHING, and finding out
whether the claim succeeded (and whether an existing row is a crashed attempt to take over)
requires reading it back, then completing it requires an UPDATE. A write-only role cannot
operate a state machine.

WHAT IS PRESERVED, and it is the part that mattered: synapse_writer STILL HAS NO SELECT ON
synapse.actions. The property was never "the writer cannot read anything" — it was "the writer
cannot read tenant data or the action log", so that a compromised or misused append credential
cannot exfiltrate either. A run row holds counts, timestamps and an outcome string. The live
test asserting the writer is denied on synapse.actions is unchanged and still passes.

NOTHING GETS INSERT ON synapse.provision. Provisioning is an operator act performed by hand
against an admin credential until a console exists, and a table that no runtime role can write
cannot be widened by a bug. The moment something needs to write it, that is a grant and a
review, not a default.

- upgrade(): apply both DDL files, then grant.
- downgrade(): drop both tables. NOTE that dropping synapse.run destroys the denominator, which
  is exactly as unreconstructable as the log itself — a day nobody recorded cannot be recovered.
  Dropping provision destroys every ``enabled_at``. Neither is recoverable from the other.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-04

"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_SCHEMAS = Path(__file__).resolve().parents[2] / "schemas" / "postgres"

_READER = "synapse_reader"
_WRITER = "synapse_writer"


def _apply(filename: str) -> None:
    """Apply a DDL file verbatim. Same helper shape as 0001, same reason: the file is the
    source of truth for schema definition and a migration that retyped it would be a second
    copy free to disagree."""
    op.execute((_SCHEMAS / filename).read_text(encoding="utf-8"))


def upgrade() -> None:
    _apply("provision.sql")
    _apply("run.sql")

    # Reader: SELECT on both. It is the identity the orchestrator enumerates with, and the one
    # anything showing an operator a tenant's run history would use.
    op.execute(f"GRANT SELECT ON synapse.provision TO {_READER}")
    op.execute(f"GRANT SELECT ON synapse.run TO {_READER}")

    # Writer: the run state machine, and nothing else. See the module docstring for why this
    # role reads here and still cannot read synapse.actions.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON synapse.run TO {_WRITER}")

    # Said in SQL rather than in a comment, because a comment cannot be re-run: the append
    # credential has no business reading or writing a customer's enablement.
    op.execute(f"REVOKE ALL ON synapse.provision FROM {_WRITER}")
    # And no DELETE anywhere. A run row is superseded by being updated, never removed; a
    # provision is disabled by setting disabled_at, never deleted.
    op.execute(f"REVOKE DELETE ON synapse.run FROM {_READER}, {_WRITER}")
    op.execute(f"REVOKE TRUNCATE ON synapse.run, synapse.provision FROM {_READER}, {_WRITER}")


def downgrade() -> None:
    # Order matters only for readability; there is no FK between them, deliberately — a run
    # must outlive the provision that caused it, or history disappears when a tenant is
    # disabled. Same lifecycle-independence argument as synapse.actions having no FK anywhere.
    op.execute("DROP TABLE IF EXISTS synapse.run")
    op.execute("DROP TABLE IF EXISTS synapse.provision")
    op.execute("DROP FUNCTION IF EXISTS synapse.provision_timezone_resolves()")
