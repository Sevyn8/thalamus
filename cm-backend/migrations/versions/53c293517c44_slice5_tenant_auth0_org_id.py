"""slice5_tenant_auth0_org_id

Revision ID: 53c293517c44
Revises: b755e9d4081c
Create Date: 2026-07-24

Client onboarding module, Slice 5 (Access & users): persist the tenant's
Auth0 Organization id so the onboarding-state resource can report a durable
``auth0_organization`` fact (TRUE/FALSE) instead of UNKNOWN.

Before this migration, ``POST /tenants/{id}/provision-auth0`` was Auth0-side
only and wrote nothing to CM, so ``GET /tenants/{id}/onboarding`` could only
answer UNKNOWN (no column stored the org id; verified in Slice 2). The Slice-6
review gate needs a durable, DB-only fact, so this adds a nullable
``auth0_org_id`` to ``core.tenants``; the provision endpoint now stamps it
after the Auth0 get-or-create, and onboarding-state derives
``auth0_organization = TRUE if auth0_org_id IS NOT NULL else FALSE``.

Additive and reversible: one nullable TEXT column, no backfill. Pre-existing
Auth0 organizations (provisioned before this column existed) read FALSE until
the idempotent provision endpoint is re-run, which stamps the id.

Unqualified identifier per the migration convention (``env.py`` sets
``search_path`` inside the alembic transaction).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "53c293517c44"
down_revision: Union[str, Sequence[str], None] = "b755e9d4081c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN auth0_org_id TEXT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE tenants DROP COLUMN auth0_org_id")
