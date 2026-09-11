"""Schema-layer tests for the client-onboarding tables.

Asserts the live database state at migration head matches the design:

- The six onboarding tables exist in the configured schema.
- ``tenant_region_enum`` gained ``INDIA`` (US, EU, INDIA in order).
- The new ``lookups`` vocabularies are seeded with the expected rows.
- RLS is enabled + forced with one ``<t>_tenant_isolation`` policy on
  each of the six tables.
- The tenant FK on a child table RESTRICTs tenant deletion.
- The 1:1 tables enforce ``UNIQUE(tenant_id)``.
- The tax-registration type-gated length CHECK rejects a bad PAN.
- RLS isolates a child table's rows across TENANT / PLATFORM contexts.

Migration upgrade / downgrade / round-trip safety was verified at
development time (``alembic upgrade head`` for both new migrations, and
the table migration reversing cleanly; the enum-add migration is
forward-only by design). These tests assert the LIVE schema at head.

LOAD-BEARING: OS1 (tables present), OS4 (RLS+FORCE+policy per table),
OS5 (FK RESTRICT), OS6 (1:1 UNIQUE), OS8 (RLS isolation).
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from admin_backend.auth.context import AuthContext
from admin_backend.config import Settings
from admin_backend.db.session import get_tenant_session


pytestmark = pytest.mark.asyncio


_ONBOARDING_TABLES = (
    "tenant_legal_profile",
    "tenant_tax_registrations",
    "tenant_billing_profile",
    "tenant_contacts",
    "tenant_documents",
    "tenant_onboarding",
)

_EXPECTED_LOOKUP_COUNTS = {
    "entity_type": 7,
    "tax_registration_type": 5,
    "document_type": 8,
    "contact_type": 4,
    "payment_terms": 6,
    "currency": 3,
}


async def _delete_children(
    session: AsyncSession, schema: str, tenant_id: UUID
) -> None:
    """Clear any onboarding child rows for a tenant so the make_tenant
    teardown's tenant DELETE (FK ON DELETE RESTRICT) succeeds."""
    for tbl in _ONBOARDING_TABLES:
        await session.execute(
            text(f"DELETE FROM {schema}.{tbl} WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )


# ---------------------------------------------------------------------------
# OS1 : six tables present at head
# ---------------------------------------------------------------------------


async def test_os1_tables_present_at_head(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
) -> None:
    """LOAD-BEARING: all six onboarding tables exist in the schema."""
    schema = settings.db_schema
    async for session in get_tenant_session(platform_auth, session_factory):
        result = await session.execute(
            text(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = :schema AND table_name = ANY(:names)
                """
            ),
            {"schema": schema, "names": list(_ONBOARDING_TABLES)},
        )
        present = {row[0] for row in result}
    assert present == set(_ONBOARDING_TABLES)


# ---------------------------------------------------------------------------
# OS2 : tenant_region_enum gained INDIA
# ---------------------------------------------------------------------------


async def test_os2_region_enum_has_india(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
) -> None:
    schema = settings.db_schema
    async for session in get_tenant_session(platform_auth, session_factory):
        result = await session.execute(
            text(
                """
                SELECT e.enumlabel
                FROM pg_type t
                JOIN pg_namespace n ON n.oid = t.typnamespace
                JOIN pg_enum e ON e.enumtypid = t.oid
                WHERE n.nspname = :schema AND t.typname = 'tenant_region_enum'
                ORDER BY e.enumsortorder
                """
            ),
            {"schema": schema},
        )
        values = tuple(row[0] for row in result)
    assert values == ("US", "EU", "INDIA")


# ---------------------------------------------------------------------------
# OS3 : lookups vocabularies seeded
# ---------------------------------------------------------------------------


async def test_os3_lookup_vocabularies_seeded(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
) -> None:
    schema = settings.db_schema
    async for session in get_tenant_session(platform_auth, session_factory):
        for list_name, expected in _EXPECTED_LOOKUP_COUNTS.items():
            result = await session.execute(
                text(
                    f"SELECT count(*) FROM {schema}.lookups "
                    "WHERE list_name = :ln"
                ),
                {"ln": list_name},
            )
            assert result.scalar_one() == expected, list_name
        # tenant_region INDIA display row present.
        india = await session.execute(
            text(
                f"SELECT count(*) FROM {schema}.lookups "
                "WHERE list_name = 'tenant_region' AND code = 'INDIA'"
            )
        )
        assert india.scalar_one() == 1


# ---------------------------------------------------------------------------
# OS4 : RLS + FORCE + one policy per table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table", _ONBOARDING_TABLES)
async def test_os4_rls_force_and_policy_present(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
    table: str,
) -> None:
    """LOAD-BEARING: each table has RLS enabled + forced + 1 policy."""
    schema = settings.db_schema
    async for session in get_tenant_session(platform_auth, session_factory):
        result = await session.execute(
            text(
                f"""
                SELECT c.relrowsecurity, c.relforcerowsecurity,
                       (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid)
                FROM pg_class c
                WHERE c.oid = '{schema}.{table}'::regclass
                """
            )
        )
        relrowsec, relforce, npol = result.one()
    assert relrowsec is True
    assert relforce is True
    assert npol == 1


# ---------------------------------------------------------------------------
# OS5 : tenant FK RESTRICTs tenant deletion
# ---------------------------------------------------------------------------


async def test_os5_tenant_fk_restricts_deletion(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
    make_tenant: Callable[..., Any],
) -> None:
    """LOAD-BEARING: a child row pins its tenant (FK ON DELETE RESTRICT)."""
    schema = settings.db_schema
    tenant = await make_tenant(name="OS5-tenant")

    async for session in get_tenant_session(platform_auth, session_factory):
        await session.execute(
            text(
                f"INSERT INTO {schema}.tenant_legal_profile "
                "(tenant_id, legal_entity_name, entity_type) "
                "VALUES (:tid, :n, :et)"
            ),
            {"tid": tenant.id, "n": "OS5 Legal Co", "et": "PRIVATE_LIMITED"},
        )

    with pytest.raises(IntegrityError):
        async for session in get_tenant_session(
            platform_auth, session_factory
        ):
            await session.execute(
                text(f"DELETE FROM {schema}.tenants WHERE id = :id"),
                {"id": tenant.id},
            )

    # Cleanup so the make_tenant teardown can delete the tenant.
    async for session in get_tenant_session(platform_auth, session_factory):
        await _delete_children(session, schema, tenant.id)


# ---------------------------------------------------------------------------
# OS6 : 1:1 UNIQUE(tenant_id) on tenant_legal_profile
# ---------------------------------------------------------------------------


async def test_os6_one_to_one_unique_tenant(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
    make_tenant: Callable[..., Any],
) -> None:
    """LOAD-BEARING: a second legal_profile row for a tenant is rejected."""
    schema = settings.db_schema
    tenant = await make_tenant(name="OS6-tenant")

    async for session in get_tenant_session(platform_auth, session_factory):
        await session.execute(
            text(
                f"INSERT INTO {schema}.tenant_legal_profile "
                "(tenant_id, legal_entity_name, entity_type) "
                "VALUES (:tid, :n, :et)"
            ),
            {"tid": tenant.id, "n": "OS6 First", "et": "LLP"},
        )

    with pytest.raises(IntegrityError):
        async for session in get_tenant_session(
            platform_auth, session_factory
        ):
            await session.execute(
                text(
                    f"INSERT INTO {schema}.tenant_legal_profile "
                    "(tenant_id, legal_entity_name, entity_type) "
                    "VALUES (:tid, :n, :et)"
                ),
                {"tid": tenant.id, "n": "OS6 Second", "et": "LLP"},
            )

    async for session in get_tenant_session(platform_auth, session_factory):
        await _delete_children(session, schema, tenant.id)


# ---------------------------------------------------------------------------
# OS7 : tax-registration type-gated length CHECK
# ---------------------------------------------------------------------------


async def test_os7_tax_pan_length_check_rejects_bad_pan(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
    make_tenant: Callable[..., Any],
) -> None:
    """PAN must be exactly 10 chars; a 9-char PAN is rejected."""
    schema = settings.db_schema
    tenant = await make_tenant(name="OS7-tenant")

    with pytest.raises(IntegrityError):
        async for session in get_tenant_session(
            platform_auth, session_factory
        ):
            await session.execute(
                text(
                    f"INSERT INTO {schema}.tenant_tax_registrations "
                    "(tenant_id, registration_type, registration_number) "
                    "VALUES (:tid, 'PAN', :num)"
                ),
                {"tid": tenant.id, "num": "SHORTPAN9"},  # 9 chars
            )

    # A non-PAN/GSTIN type is unconstrained on length; insert + cleanup.
    async for session in get_tenant_session(platform_auth, session_factory):
        await session.execute(
            text(
                f"INSERT INTO {schema}.tenant_tax_registrations "
                "(tenant_id, registration_type, registration_number) "
                "VALUES (:tid, 'VAT', :num)"
            ),
            {"tid": tenant.id, "num": "VAT-ANY-LENGTH-OK"},
        )
    async for session in get_tenant_session(platform_auth, session_factory):
        await _delete_children(session, schema, tenant.id)


# ---------------------------------------------------------------------------
# OS8 : RLS isolates a child table's rows across contexts
# ---------------------------------------------------------------------------


async def test_os8_child_table_rls_isolation(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
    tenant_session_factory: Callable[
        [UUID], AbstractAsyncContextManager[AsyncSession]
    ],
    make_tenant: Callable[..., Any],
) -> None:
    """LOAD-BEARING: TENANT-B cannot see TENANT-A's tenant_contacts row."""
    schema = settings.db_schema
    tenant_a = await make_tenant(name="OS8-A")
    tenant_b = await make_tenant(name="OS8-B")

    async for session in get_tenant_session(platform_auth, session_factory):
        await session.execute(
            text(
                f"INSERT INTO {schema}.tenant_contacts "
                "(tenant_id, contact_type, name) "
                "VALUES (:tid, 'PRIMARY', :n)"
            ),
            {"tid": tenant_a.id, "n": "A Contact"},
        )

    async with tenant_session_factory(tenant_a.id) as session:
        seen_a = (
            await session.execute(
                text(
                    f"SELECT count(*) FROM {schema}.tenant_contacts"
                )
            )
        ).scalar_one()
    async with tenant_session_factory(tenant_b.id) as session:
        seen_b = (
            await session.execute(
                text(
                    f"SELECT count(*) FROM {schema}.tenant_contacts"
                )
            )
        ).scalar_one()

    assert seen_a == 1
    assert seen_b == 0

    async for session in get_tenant_session(platform_auth, session_factory):
        await _delete_children(session, schema, tenant_a.id)
