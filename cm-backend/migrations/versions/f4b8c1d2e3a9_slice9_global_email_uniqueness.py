"""slice9_global_email_uniqueness

Revision ID: f4b8c1d2e3a9
Revises: 53c293517c44
Create Date: 2026-07-25

Slice 9 (one email = one identity). Replace the per-tenant
UNIQUE(tenant_id, email) on ``tenant_users`` with a GLOBAL UNIQUE(email),
and fail the migration up front if existing data would violate the rule.

Product decision (final): an email may belong to exactly ONE entity
platform-wide, either one platform user OR one tenant user of exactly one
tenant. The prior "same human across tenants = two rows" intent
documented in the tenant_users DDL is OVERTURNED. Tenants are separate
legal entities; identity must not straddle a legal/trust boundary.

Cross-TABLE uniqueness (platform_users vs tenant_users) cannot be a single
SQL constraint; it is enforced at the application layer
(``TenantUsersRepo._raise_if_email_in_use`` + the platform_users-side
SELECT). This migration only enforces the tenant_users side structurally.

Pre-flight (upgrade): detects (a) emails appearing in more than one
tenant_users row (cross-tenant, since the old per-tenant unique already
blocked same-tenant dups) and (b) emails present in BOTH platform_users
and tenant_users, and RAISES with a full listing rather than mutating any
row. The operator resolves duplicates (delete one side) BEFORE deploying;
this migration never deletes or merges data.

RLS: migrations connect as a NOBYPASSRLS role, so ``tenant_users`` reads
are RLS-filtered. The pre-flight sets ``app.user_type='PLATFORM'``
(transaction-local) so the D-29 PLATFORM OR-branch makes every
tenant_users row visible; without this the detection would see zero rows
and falsely pass.

Schema-qualified via ``current_schema()`` capture per CSD-03.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

# revision identifiers, used by Alembic.
revision: str = "f4b8c1d2e3a9"
down_revision: Union[str, Sequence[str], None] = "53c293517c44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


class EmailUniquenessViolation(RuntimeError):
    """Raised when existing data would violate one-email-one-identity."""


def detect_email_violations(
    bind: Connection, schema: str
) -> tuple[list[tuple[str, int]], list[str]]:
    """Return ``(cross_tenant_dupes, platform_tenant_overlaps)``.

    ``cross_tenant_dupes``: ``(email, row_count)`` for emails present in
    more than one ``tenant_users`` row. ``platform_tenant_overlaps``:
    emails present in BOTH ``platform_users`` and ``tenant_users``.

    Caller MUST have set ``app.user_type='PLATFORM'`` first so
    ``tenant_users`` is fully visible under RLS; otherwise the tenant-side
    reads are silently empty.
    """
    dupes = bind.execute(
        sa.text(
            f"SELECT email, COUNT(*) AS c FROM {schema}.tenant_users "
            "GROUP BY email HAVING COUNT(*) > 1 ORDER BY email"
        )
    ).fetchall()
    overlaps = bind.execute(
        sa.text(
            f"SELECT p.email FROM {schema}.platform_users p "
            f"WHERE EXISTS (SELECT 1 FROM {schema}.tenant_users t "
            "WHERE t.email = p.email) ORDER BY p.email"
        )
    ).fetchall()
    return (
        [(str(r.email), int(r.c)) for r in dupes],
        [str(r.email) for r in overlaps],
    )


def _format_violations(
    dupes: list[tuple[str, int]], overlaps: list[str]
) -> str:
    lines = [
        "Slice 9 pre-flight: existing data violates one-email-one-identity.",
        "Resolve these BEFORE deploying (delete one side; this migration "
        "touches no rows).",
    ]
    if dupes:
        lines.append("Emails in more than one tenant_users row (cross-tenant):")
        lines.extend(f"  - {email} ({count} rows)" for email, count in dupes)
    if overlaps:
        lines.append(
            "Emails present in BOTH platform_users and tenant_users:"
        )
        lines.extend(f"  - {email}" for email in overlaps)
    return "\n".join(lines)


def upgrade() -> None:
    bind = op.get_bind()
    schema = bind.execute(sa.text("SELECT current_schema()")).scalar_one()
    # RLS visibility for the pre-flight (see module docstring). Transaction
    # -local; alembic runs the migration in a transaction.
    bind.execute(
        sa.text("SELECT set_config('app.user_type', 'PLATFORM', true)")
    )
    dupes, overlaps = detect_email_violations(bind, schema)
    if dupes or overlaps:
        raise EmailUniquenessViolation(_format_violations(dupes, overlaps))

    op.execute(f"DROP INDEX IF EXISTS {schema}.uq_tenant_users_tenant_email")
    op.execute(
        f"CREATE UNIQUE INDEX uq_tenant_users_email "
        f"ON {schema}.tenant_users (email)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    schema = bind.execute(sa.text("SELECT current_schema()")).scalar_one()
    op.execute(f"DROP INDEX IF EXISTS {schema}.uq_tenant_users_email")
    op.execute(
        f"CREATE UNIQUE INDEX uq_tenant_users_tenant_email "
        f"ON {schema}.tenant_users (tenant_id, email)"
    )
