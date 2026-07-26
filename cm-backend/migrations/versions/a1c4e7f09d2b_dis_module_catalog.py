"""dis_module_catalog

Revision ID: a1c4e7f09d2b
Revises: f4b8c1d2e3a9
Create Date: 2026-07-24

Add DIS (Data Integration System) to the module catalog so it is
grantable per tenant via Module Access, exactly like the other product
modules. Two additive changes:

  1. ``ALTER TYPE module_code_enum ADD VALUE 'DIS'`` so the enable /
     disable endpoints (which CAST the path param to
     ``module_code_enum``) and the ``ModuleCode`` ORM enum accept DIS.
  2. One ``lookups`` row (``list_name='module_code'``, ``code='DIS'``,
     ``display_name='DIS'``, ``display_order=7``). The read endpoints
     (/module-access/modules, /matrix, /me) are lookups-driven, so DIS
     surfaces automatically from this row.

DIS is NOT force-enabled: no ``tenant_module_access`` row is seeded, so
DIS is default DISABLED for every tenant and can only be turned on via
the existing enable endpoint (contrast ADMIN, which is granted per the
seed).

``description`` is left NULL: the module catalog convention is
display_name only (every existing ``module_code`` row leaves description
NULL). ``display_order=7`` appends DIS after ADMIN (=6); ROOS (=1) was
retired from the local/wire vocabulary by the seed loader's --reset, so
the effective order is GOAL_CONSOLE(2) .. ADMIN(6), DIS(7).

``ADD VALUE`` cannot run inside a transaction block that later uses the
new value, and Alembic wraps each migration in a transaction; the robust
idiom is an autocommit block so the ALTER commits independently
(mirrors ``d3f7a1c92b64``). The lookups INSERT writes a text ``code`` (not
the enum), so the same-transaction-use restriction does not apply to it.
``IF NOT EXISTS`` + ``ON CONFLICT DO NOTHING`` make the upgrade
idempotent.

Forward-only per the project's irreversible-enum convention (precedents
``d3f7a1c92b64``, ``90cd038ae618``, ``cec8fae734e0``): removing an enum
value needs the rename-recreate-cast dance. ``downgrade`` raises
``NotImplementedError``.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c4e7f09d2b"
down_revision: Union[str, Sequence[str], None] = "f4b8c1d2e3a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add DIS to module_code_enum (autocommit) + seed its lookups row."""
    # 1. Extend the enum (independent commit; idempotent).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE module_code_enum ADD VALUE IF NOT EXISTS 'DIS'")

    # 2. Seed the catalog row (idempotent). display_name only, per the
    #    module catalog convention (description left NULL like every
    #    existing module_code row).
    op.execute(
        """
        INSERT INTO lookups (list_name, code, display_name, display_order, is_active)
        VALUES ('module_code', 'DIS', 'DIS', 7, TRUE)
        ON CONFLICT (list_name, code) DO NOTHING
        """
    )


def downgrade() -> None:
    """Irreversible: removing an enum value needs rename-recreate-cast."""
    raise NotImplementedError(
        "Removing 'DIS' from module_code_enum is not supported "
        "(forward-only enum change; mirrors the project's "
        "irreversible-cleanup convention, e.g. d3f7a1c92b64)."
    )
