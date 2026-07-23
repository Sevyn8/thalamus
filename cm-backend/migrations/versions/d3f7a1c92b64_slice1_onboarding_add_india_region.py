"""slice1_onboarding_add_india_region

Revision ID: d3f7a1c92b64
Revises: 7a3c8e9d2f5b
Create Date: 2026-07-23

Client onboarding module, Slice 1 (migration 1 of 2).

Adds ``INDIA`` to ``tenant_region_enum``. This is the first
``ALTER TYPE ... ADD VALUE`` in the migration chain (all prior enum
changes were narrowings via rename-recreate-cast). ``ADD VALUE`` cannot
run inside a transaction block that later uses the new value, and
Alembic wraps each migration in a transaction; the robust idiom is to
run the statement in an autocommit block so it commits independently.
The new value is NOT used in this migration or the next (the lookups
seed in migration 2 inserts a text ``code``, not the enum), so the
same-transaction-use restriction is not a concern regardless.

``IF NOT EXISTS`` makes the upgrade idempotent (Postgres 12+).

Forward-only per flag 5a: removing an enum value requires the
rename-recreate-cast dance, matching the project's irreversible-cleanup
convention (precedents ``90cd038ae618``, ``cec8fae734e0``). ``downgrade``
raises ``NotImplementedError``.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d3f7a1c92b64"
down_revision: Union[str, Sequence[str], None] = "7a3c8e9d2f5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add INDIA to tenant_region_enum (autocommit; idempotent)."""
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE tenant_region_enum ADD VALUE IF NOT EXISTS 'INDIA'"
        )


def downgrade() -> None:
    """Irreversible: removing an enum value needs rename-recreate-cast."""
    raise NotImplementedError(
        "Removing 'INDIA' from tenant_region_enum is not supported "
        "(forward-only enum change per flag 5a; mirrors the project's "
        "irreversible-cleanup convention)."
    )
