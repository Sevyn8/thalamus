"""Reset synapse.actions once, while it costs nothing

WHY THIS EXISTS. Synapse's integration tests appended to the action log under the REAL tenant,
because the synthetic probe tenant did not exist yet. Four rows landed in staging that way —
``SKU-IDEMPOTENCY-*`` and ``SKU-CROSS-TENANT`` events from the idempotency and cross-tenant
tests. They are test data sitting in a production tenant's stream, and the table is append-only
by trigger, so nothing short of the owner disabling that trigger can remove them.

THE TABLE CONTAINED NOTHING ELSE. Those four rows were the entire contents of the log: it was
created in slice 5, nothing in production writes to it, and no analysis has yet emitted an
action. That is what makes this migration safe, and it is a property with an expiry date —
**this is the only free moment.** The instant anything real is appended, a reset like this one
destroys history that cannot be reconstructed, because an append-only log has no other copy.

So it is done now, once, and written down. The manual route works — the owner can drop the
trigger, delete, and recreate it in a psql session — but that is the documented escape hatch
used unrecorded, and "the action log was reset, and here is why" needs to be discoverable in six
months by someone reading the chain rather than a chat transcript.

TWO THINGS MAKE THIS LESS OBVIOUS THAN `DELETE FROM synapse.actions`:

1. **THE TRIGGER REFUSES DELETE, INCLUDING FROM THE OWNER.** That is the point of it. So the
   migration disables it for the duration and re-enables it in the same transaction. Postgres
   DDL is transactional, so a failure anywhere in between rolls the disable back too — the
   table cannot be left unguarded by a half-applied migration.

2. **RLS HIDES THE ROWS FROM THE OWNER.** ``synapse.actions`` is FORCE ROW LEVEL SECURITY, and
   Cloud SQL's ``postgres`` is NOSUPERUSER NOBYPASSRLS like anything else, so a bare DELETE here
   matches ZERO rows and reports success. This cost a whole investigation once already: a
   ``SELECT count(*)`` returning 0 was read as an empty table when the rows were merely
   invisible. The policy's USING clause admits ``app.user_type = 'PLATFORM'``, so the migration
   sets that GUC transaction-locally rather than weakening the policy.

SURGICAL, NOT A RECREATION. Dropping and recreating the table would also discard its grants,
its policy, its indexes and its trigger — a far larger blast radius than four rows justify, and
four more things to get right.

- upgrade(): set PLATFORM scope, disable the append-only trigger, DELETE, re-enable, verify
  empty. Refuses to run if the log holds more rows than a test suite could plausibly have
  produced (see ``_MAX_EXPECTED``) — the guard against this migration reaching a database whose
  log has become real.
- downgrade(): a no-op that RAISES. The deleted rows cannot be restored; pretending otherwise
  with an empty ``pass`` would make ``downgrade`` look reversible when it is the one operation
  in this chain that is not.

VERIFY IN THE SAME WINDOW, with the GUCs set, or the answer is 0 either way:

    BEGIN;
      SELECT set_config('app.user_type','TENANT',true);
      SELECT set_config('app.tenant_id','<REAL_TENANT>',true);
      SELECT count(*) FROM synapse.actions;   -- must be 0
    ROLLBACK;

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-04

"""

from __future__ import annotations

from sqlalchemy import text

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# The log has never been written by anything but tests, which produce a handful of rows per run.
# A hundred is far above that and far below any real volume, so it separates "this is still the
# test-only log this migration was written for" from "something has started using it". The
# number is a judgement, not a measurement, which is why exceeding it stops rather than deletes.
_MAX_EXPECTED = 100

_TRIGGER = "trg_actions_append_only"


def upgrade() -> None:
    conn = op.get_bind()

    # PLATFORM scope, transaction-local. Without it every statement below silently addresses an
    # empty table: FORCE RLS applies to the owner, and this connection sets no tenant.
    conn.execute(text("SELECT set_config('app.user_type', 'PLATFORM', true)"))

    before = int(conn.execute(text("SELECT count(*) FROM synapse.actions")).scalar_one())
    if before > _MAX_EXPECTED:
        raise RuntimeError(
            f"synapse.actions holds {before} rows, more than the {_MAX_EXPECTED} this migration "
            "expects of a test-only log. It resets the log by design, and it was written for a "
            "moment when the table held four test rows and nothing else. If these rows are real "
            "actions, DO NOT run this - delete it from the chain instead. If they are still test "
            "rows, raise _MAX_EXPECTED deliberately and say why in the commit."
        )

    op.execute(f"ALTER TABLE synapse.actions DISABLE TRIGGER {_TRIGGER}")
    try:
        op.execute("DELETE FROM synapse.actions")
    finally:
        # In the same transaction either way. An exception rolls the DISABLE back with it, but
        # re-enabling explicitly means the table is never left unguarded even if a future edit
        # to this function commits between the two.
        op.execute(f"ALTER TABLE synapse.actions ENABLE TRIGGER {_TRIGGER}")

    after = int(conn.execute(text("SELECT count(*) FROM synapse.actions")).scalar_one())
    if after:
        raise RuntimeError(
            f"deleted {before} rows from synapse.actions and {after} remain. The DELETE was "
            "scoped by something unexpected - check whether the PLATFORM GUC took effect"
        )

    # The trigger must be back on before this transaction commits. Checked rather than assumed:
    # leaving the log mutable is a worse outcome than failing the migration.
    enabled = conn.execute(
        text(
            "SELECT tgenabled FROM pg_trigger WHERE tgname = :name AND tgrelid = 'synapse.actions'::regclass"
        ),
        {"name": _TRIGGER},
    ).scalar_one()
    if enabled != "O":
        raise RuntimeError(
            f"{_TRIGGER} is in state {enabled!r} rather than 'O' after this migration. The "
            "append-only guarantee is off; do not commit this transaction"
        )


def downgrade() -> None:
    raise RuntimeError(
        "0002 deleted rows from an append-only log and cannot restore them - there is no other "
        "copy, which is the whole premise of the table. Downgrading past this point means "
        "0001's DROP SCHEMA, which destroys the log anyway. This raises rather than passing "
        "silently so that nobody reads a clean `alembic downgrade` as having undone it."
    )
