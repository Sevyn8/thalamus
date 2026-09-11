"""Migration-shape tests for tenant_documents verification.

Asserts the migration b755e9d4081c is applied: the six new columns exist
with the right nullability, the verification-consistency CHECK enforces the
state machine at the DB layer, and the document_verification_status lookups
vocabulary is seeded. The upgrade/downgrade round-trip itself is verified
out-of-band (alembic downgrade -1 / upgrade head); this locks the
as-applied shape in the suite.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from admin_backend.auth.context import AuthContext
from admin_backend.config import get_settings
from admin_backend.db.session import get_tenant_session

pytestmark = pytest.mark.asyncio


async def _insert_document(
    session: AsyncSession, tenant_id: UUID, **cols: object
) -> None:
    schema = get_settings().db_schema
    base = {
        "tenant_id": tenant_id,
        "document_type": "PAN_CARD",
        "gcs_object_uri": "gs://b/tenants/x/documents/u/f.pdf",
        "verification_status": "PENDING_REVIEW",
    }
    base.update(cols)
    keys = ", ".join(base.keys())
    binds = ", ".join(f":{k}" for k in base)
    await session.execute(
        text(f"INSERT INTO {schema}.tenant_documents ({keys}) VALUES ({binds})"),
        base,
    )


async def test_at1_columns_present_with_nullability(
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
) -> None:
    schema = get_settings().db_schema
    async for session in get_tenant_session(platform_auth, session_factory):
        rows = (
            await session.execute(
                text(
                    """
                    SELECT column_name, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = :schema
                      AND table_name = 'tenant_documents'
                      AND column_name IN (
                        'verification_status', 'verified_by_user_id',
                        'verified_at', 'rejection_reason',
                        'file_size_bytes', 'uploaded_by_user_id'
                      )
                    """
                ),
                {"schema": schema},
            )
        ).all()
        nullability = {r.column_name: r.is_nullable for r in rows}
    assert nullability == {
        "verification_status": "NO",
        "verified_by_user_id": "YES",
        "verified_at": "YES",
        "rejection_reason": "YES",
        "file_size_bytes": "YES",
        "uploaded_by_user_id": "YES",
    }


async def test_at2_lookups_seeded(
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
) -> None:
    schema = get_settings().db_schema
    async for session in get_tenant_session(platform_auth, session_factory):
        codes = (
            await session.execute(
                text(
                    f"SELECT code FROM {schema}.lookups "
                    "WHERE list_name = 'document_verification_status' "
                    "ORDER BY display_order"
                )
            )
        ).scalars().all()
    assert list(codes) == ["PENDING_REVIEW", "VERIFIED", "REJECTED"]


async def test_at3_default_status_is_pending_review(
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
    make_tenant,
    cleanup_documents,
) -> None:
    schema = get_settings().db_schema
    tenant = await make_tenant(name="AT3")
    cleanup_documents.append(tenant.id)
    async for session in get_tenant_session(platform_auth, session_factory):
        # Omit verification_status entirely -> DDL default fires.
        await session.execute(
            text(
                f"INSERT INTO {schema}.tenant_documents "
                "(tenant_id, document_type, gcs_object_uri) "
                "VALUES (:tid, 'PAN_CARD', 'gs://b/x')"
            ),
            {"tid": tenant.id},
        )
        status = (
            await session.execute(
                text(
                    f"SELECT verification_status FROM {schema}.tenant_documents "
                    "WHERE tenant_id = :tid"
                ),
                {"tid": tenant.id},
            )
        ).scalar_one()
    assert status == "PENDING_REVIEW"


async def test_at4_check_rejects_verified_without_verifier(
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
    make_tenant,
    cleanup_documents,
) -> None:
    """LOAD-BEARING: the DB CHECK backstops the app state machine -
    VERIFIED requires verified_by_user_id + verified_at."""
    tenant = await make_tenant(name="AT4")
    cleanup_documents.append(tenant.id)
    with pytest.raises(IntegrityError):
        async for session in get_tenant_session(
            platform_auth, session_factory
        ):
            await _insert_document(
                session, tenant.id, verification_status="VERIFIED"
            )


async def test_at5_check_rejects_rejected_without_reason(
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
    make_tenant,
    make_platform_user,
    cleanup_documents,
) -> None:
    """REJECTED requires verified_by/verified_at AND rejection_reason;
    supplying the verifier pair but no reason still violates the CHECK."""
    tenant = await make_tenant(name="AT5")
    cleanup_documents.append(tenant.id)
    actor = await make_platform_user(status="ACTIVE")
    with pytest.raises(IntegrityError):
        async for session in get_tenant_session(
            platform_auth, session_factory
        ):
            await _insert_document(
                session,
                tenant.id,
                verification_status="REJECTED",
                verified_by_user_id=actor.id,
                verified_at=datetime.now(timezone.utc),
                # rejection_reason omitted -> CHECK violation.
            )
