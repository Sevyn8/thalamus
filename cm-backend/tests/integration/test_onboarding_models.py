"""ORM round-trip tests for the client-onboarding models.

Each test inserts one row via the ORM model under a PLATFORM session,
flushes + refreshes to pull the DB-side defaults (``uuidv7()`` id,
``created_at`` / ``updated_at``, and ``section_status`` for onboarding),
asserts the mapping, then deletes the row before the block commits so
the ``make_tenant`` teardown's tenant DELETE (FK ON DELETE RESTRICT)
succeeds.

OM7 exercises the ``INDIA`` region end-to-end: a tenant created
with ``TenantRegion.INDIA`` persists and reads back.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from admin_backend.auth.context import AuthContext
from admin_backend.config import Settings
from admin_backend.db.session import get_tenant_session
from admin_backend.models import (
    TenantBillingProfile,
    TenantContact,
    TenantDocument,
    TenantLegalProfile,
    TenantOnboarding,
    TenantTaxRegistration,
)
from admin_backend.models.tenant import TenantRegion


pytestmark = pytest.mark.asyncio


async def test_om1_legal_profile_roundtrip(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
    make_tenant: Callable[..., Any],
) -> None:
    tenant = await make_tenant(name="OM1-legal")
    async for session in get_tenant_session(platform_auth, session_factory):
        obj = TenantLegalProfile(
            tenant_id=tenant.id,
            legal_entity_name="OM1 Legal Co",
            entity_type="PRIVATE_LIMITED",
        )
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        assert obj.id is not None
        assert obj.created_at is not None
        assert obj.updated_at is not None
        assert obj.legal_entity_name == "OM1 Legal Co"
        assert obj.entity_type == "PRIVATE_LIMITED"
        await session.delete(obj)
        await session.flush()


async def test_om2_tax_registration_roundtrip(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
    make_tenant: Callable[..., Any],
) -> None:
    tenant = await make_tenant(name="OM2-tax")
    async for session in get_tenant_session(platform_auth, session_factory):
        obj = TenantTaxRegistration(
            tenant_id=tenant.id,
            registration_type="GSTIN",
            registration_number="27AAPFU0939F1ZV",  # 15 chars
            jurisdiction="Maharashtra",
        )
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        assert obj.id is not None
        assert obj.registration_type == "GSTIN"
        assert obj.jurisdiction == "Maharashtra"
        await session.delete(obj)
        await session.flush()


async def test_om3_billing_profile_roundtrip(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
    make_tenant: Callable[..., Any],
) -> None:
    tenant = await make_tenant(name="OM3-billing")
    async for session in get_tenant_session(platform_auth, session_factory):
        obj = TenantBillingProfile(
            tenant_id=tenant.id,
            payment_terms="NET_30",
            currency="INR",
            billing_email="billing@test.example.com",
        )
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        assert obj.id is not None
        assert obj.payment_terms == "NET_30"
        assert obj.currency == "INR"
        await session.delete(obj)
        await session.flush()


async def test_om4_contact_roundtrip(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
    make_tenant: Callable[..., Any],
) -> None:
    tenant = await make_tenant(name="OM4-contact")
    async for session in get_tenant_session(platform_auth, session_factory):
        obj = TenantContact(
            tenant_id=tenant.id,
            contact_type="TECHNICAL",
            name="Dana Ops",
            email="dana@test.example.com",
        )
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        assert obj.id is not None
        assert obj.contact_type == "TECHNICAL"
        await session.delete(obj)
        await session.flush()


async def test_om5_document_roundtrip(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
    make_tenant: Callable[..., Any],
) -> None:
    tenant = await make_tenant(name="OM5-doc")
    async for session in get_tenant_session(platform_auth, session_factory):
        obj = TenantDocument(
            tenant_id=tenant.id,
            document_type="TAX_CERTIFICATE",
            gcs_object_uri="gs://bucket/tenant/doc.pdf",
            file_name="doc.pdf",
        )
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        assert obj.id is not None
        assert obj.gcs_object_uri == "gs://bucket/tenant/doc.pdf"
        await session.delete(obj)
        await session.flush()


async def test_om6_onboarding_roundtrip_defaults_section_status(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
    make_tenant: Callable[..., Any],
) -> None:
    tenant = await make_tenant(name="OM6-onboarding")
    async for session in get_tenant_session(platform_auth, session_factory):
        obj = TenantOnboarding(tenant_id=tenant.id)
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        assert obj.id is not None
        # section_status defaults to '{}' via the DDL (FetchedValue).
        assert obj.section_status == {}
        assert obj.completed_at is None
        assert obj.completed_by_user_id is None
        await session.delete(obj)
        await session.flush()


async def test_om7_tenant_region_india_roundtrip(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
    make_tenant: Callable[..., Any],
) -> None:
    """INDIA region persists + reads back end-to-end (Python enum + DB enum)."""
    tenant = await make_tenant(name="OM7-india", region=TenantRegion.INDIA)
    assert tenant.region == TenantRegion.INDIA
