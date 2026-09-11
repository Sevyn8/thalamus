"""TRUNCATE-all-at-once for the ``--reset`` flag.

Postgres rejects ``TRUNCATE foo`` when *any* other table has an FK
referencing ``foo`` — even when the referencing table happens to be
empty (PG checks the constraint's existence, not the row count).
The standard fix without CASCADE is to list all the dependent
tables in a single ``TRUNCATE`` statement; Postgres resolves the FK
dependency graph across the set internally.

`tenant_activity_audit_logs` and `platform_activity_audit_logs` both
FK to `tenants(id)`, so they have to be co-listed for the
TRUNCATE-without-CASCADE resolution to succeed (Postgres validates
the FK graph across the listed tables as one operation, regardless
of row counts).
`lookups` is not in the list, it carries the migration-seeded
`module_code` rows that the seed loader expects to be present.

A TRUNCATE that needs CASCADE is a sign of either wrong ordering or
wrong scope; a single multi-table TRUNCATE without CASCADE is the
project-shaped solution.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# All seed-loader tables in one TRUNCATE statement. Postgres resolves
# the FK constraints across this set as a single operation.
#
# platform_user_role_assignments (no RLS) and
# tenant_user_role_assignments (RLS+FORCE, composite FKs) are both
# leaf tables (no inbound FKs from other seed tables).
SEED_TABLES = [
    "tenant_activity_audit_logs",
    "platform_activity_audit_logs",
    "tenant_module_access",
    "platform_user_role_assignments",
    "tenant_user_role_assignments",
    "role_permissions",
    "permissions",
    "roles",
    "stores",
    "org_nodes",
    # Onboarding tables: all FK to tenants(id), so they must be
    # co-listed with tenants for the TRUNCATE-without-CASCADE resolution.
    # The seed loader does not populate them; they ship empty and the
    # TRUNCATE is a no-op, but co-listing is required so TRUNCATE tenants
    # does not raise "cannot truncate a table referenced in a foreign key".
    "tenant_legal_profile",
    "tenant_tax_registrations",
    "tenant_billing_profile",
    "tenant_contacts",
    "tenant_documents",
    "tenant_onboarding",
    "tenant_users",
    "tenants",
    "platform_users",
]


async def truncate_seed_tables(session: AsyncSession) -> None:
    """TRUNCATE all seed tables in one statement. NO CASCADE.

    Shares the caller's transaction (the runner's
    ``get_tenant_session`` block); commit happens on clean exit.
    """
    await session.execute(
        text(
            "TRUNCATE "
            + ", ".join(SEED_TABLES)
            + " RESTART IDENTITY"
        )
    )
