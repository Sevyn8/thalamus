"""Data access for tenant onboarding documents (Slice 3).

One ``DocumentsRepo`` covering the document rows on ``tenant_documents``.
Raw ``text()`` SQL, every identifier schema-qualified via
``get_settings().db_schema`` per CSD-03; RLS-bound through the session
GUCs (PLATFORM callers see all rows via the D-29 OR-branch; the endpoints
are PLATFORM-audience-gated anyway).

Write methods emit exactly one audit event per call via
``emit_audit_event`` (resource_type TENANT, mirroring the Slice-2
onboarding repo). ``auth`` + ``request_id`` are optional and
both-or-neither: repo-level tests may omit them to skip emission.

``document_type`` is validated against the ACTIVE ``document_type``
``core.lookups`` rows; an invalid code raises ``InvalidLookupCodeError``
(422) before any write. The verify / reject / delete state machine is
PENDING_REVIEW-gated; a wrong-status action raises
``InvalidDocumentStateError`` (409). A missing / cross-tenant document id
raises ``DocumentNotFoundError`` (404, RLS-as-404 per D-17).

Object-content never flows through this service; only the ``gcs_object_uri``
reference is stored. Signed URLs are minted by the GCS seam in the router.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession

from admin_backend.audit.emit import (
    build_success_details_for_create,
    emit_audit_event,
)
from admin_backend.auth.context import AuthContext
from admin_backend.config import get_settings
from admin_backend.errors import (
    DocumentNotFoundError,
    InvalidDocumentStateError,
    InvalidLookupCodeError,
    TenantNotFoundError,
)
from admin_backend.models import AuditResultType
from admin_backend.repositories.lookups import LookupsRepo

_lookups_repo = LookupsRepo()

# Columns projected into DocumentRead (id + metadata + verification state).
_READ_COLS = (
    "id, document_type, file_name, content_type, file_size_bytes, "
    "verification_status, verified_at, rejection_reason, created_at"
)


def _emit_args_valid(
    auth: AuthContext | None, request_id: UUID | None
) -> bool:
    if (auth is None) != (request_id is None):
        raise ValueError(
            "auth and request_id must be provided together for audit "
            "emission, or both omitted"
        )
    return auth is not None and request_id is not None


class DocumentsRepo:
    """Read + write access for tenant documents."""

    async def tenant_name_or_none(
        self, session: AsyncSession, tenant_id: UUID
    ) -> str | None:
        schema = get_settings().db_schema
        result = await session.execute(
            text(f"SELECT name FROM {schema}.tenants WHERE id = :tid"),
            {"tid": tenant_id},
        )
        row = result.first()
        return str(row.name) if row is not None else None

    async def _require_tenant(
        self, session: AsyncSession, tenant_id: UUID
    ) -> str:
        name = await self.tenant_name_or_none(session, tenant_id)
        if name is None:
            raise TenantNotFoundError(
                f"Tenant {tenant_id} not visible to this session",
                tenant_id=str(tenant_id),
            )
        return name

    async def _validate_document_type(
        self, session: AsyncSession, document_type: str
    ) -> None:
        active = await _lookups_repo.get_lists_batch(session, ["document_type"])
        codes = {row.code for row in active.get("document_type", [])}
        if document_type not in codes:
            raise InvalidLookupCodeError(
                field="document_type",
                value=document_type,
                list_name="document_type",
            )

    # ------------------------------------------------------------------
    # Create (PENDING_REVIEW) + reads
    # ------------------------------------------------------------------

    async def create_pending(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        *,
        document_type: str,
        file_name: str,
        content_type: str,
        file_size_bytes: int,
        gcs_object_uri: str,
        actor_user_id: UUID,
        auth: AuthContext | None = None,
        request_id: UUID | None = None,
    ) -> Row[Any]:
        schema = get_settings().db_schema
        tenant_name = await self._require_tenant(session, tenant_id)
        await self._validate_document_type(session, document_type)

        result = await session.execute(
            text(
                f"""
                INSERT INTO {schema}.tenant_documents (
                    tenant_id, document_type, gcs_object_uri, file_name,
                    content_type, file_size_bytes, uploaded_by_user_id,
                    created_by_user_id, updated_by_user_id
                ) VALUES (
                    :tid, :dtype, :uri, :fname, :ctype, :size, :actor,
                    :actor, :actor
                )
                RETURNING {_READ_COLS}
                """
            ),
            {
                "tid": tenant_id,
                "dtype": document_type,
                "uri": gcs_object_uri,
                "fname": file_name,
                "ctype": content_type,
                "size": file_size_bytes,
                "actor": actor_user_id,
            },
        )
        row = result.first()
        assert row is not None  # RETURNING always yields a row
        await self._emit(
            session,
            auth=auth,
            request_id=request_id,
            action="CREATE_DOCUMENT",
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            snapshot={
                "resource": "document",
                "document_id": str(row.id),
                "document_type": document_type,
                "verification_status": row.verification_status,
            },
        )
        return row

    async def list(
        self, session: AsyncSession, tenant_id: UUID
    ) -> list[Row[Any]]:
        schema = get_settings().db_schema
        result = await session.execute(
            text(
                f"""
                SELECT {_READ_COLS}
                FROM {schema}.tenant_documents
                WHERE tenant_id = :tid
                ORDER BY created_at DESC, id DESC
                """
            ),
            {"tid": tenant_id},
        )
        return list(result.all())

    async def get(
        self, session: AsyncSession, tenant_id: UUID, document_id: UUID
    ) -> Row[Any] | None:
        """Return the row (read cols + gcs_object_uri for download), or
        None if the document is not visible for this tenant."""
        schema = get_settings().db_schema
        result = await session.execute(
            text(
                f"""
                SELECT {_READ_COLS}, gcs_object_uri
                FROM {schema}.tenant_documents
                WHERE tenant_id = :tid AND id = :did
                """
            ),
            {"tid": tenant_id, "did": document_id},
        )
        return result.first()

    # ------------------------------------------------------------------
    # Verification state machine (verify / reject / delete)
    # ------------------------------------------------------------------

    async def _select_for_update_status(
        self, session: AsyncSession, tenant_id: UUID, document_id: UUID
    ) -> str | None:
        schema = get_settings().db_schema
        result = await session.execute(
            text(
                f"""
                SELECT verification_status
                FROM {schema}.tenant_documents
                WHERE tenant_id = :tid AND id = :did
                FOR UPDATE
                """
            ),
            {"tid": tenant_id, "did": document_id},
        )
        row = result.first()
        return str(row.verification_status) if row is not None else None

    async def verify(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        document_id: UUID,
        *,
        actor_user_id: UUID,
        auth: AuthContext | None = None,
        request_id: UUID | None = None,
    ) -> Row[Any]:
        schema = get_settings().db_schema
        tenant_name = await self._require_tenant(session, tenant_id)
        current = await self._select_for_update_status(
            session, tenant_id, document_id
        )
        if current is None:
            raise DocumentNotFoundError(
                document_id=str(document_id), tenant_id=str(tenant_id)
            )
        if current != "PENDING_REVIEW":
            raise InvalidDocumentStateError(
                current_status=current, action="verify"
            )

        result = await session.execute(
            text(
                f"""
                UPDATE {schema}.tenant_documents SET
                    verification_status = 'VERIFIED',
                    verified_by_user_id = :actor,
                    verified_at = now(),
                    rejection_reason = NULL,
                    updated_by_user_id = :actor,
                    updated_at = now()
                WHERE tenant_id = :tid AND id = :did
                RETURNING {_READ_COLS}
                """
            ),
            {"tid": tenant_id, "did": document_id, "actor": actor_user_id},
        )
        row = result.first()
        assert row is not None
        await self._emit(
            session,
            auth=auth,
            request_id=request_id,
            action="VERIFY_DOCUMENT",
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            snapshot={
                "resource": "document",
                "document_id": str(document_id),
                "verification_status": "VERIFIED",
            },
        )
        return row

    async def reject(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        document_id: UUID,
        *,
        rejection_reason: str,
        actor_user_id: UUID,
        auth: AuthContext | None = None,
        request_id: UUID | None = None,
    ) -> Row[Any]:
        schema = get_settings().db_schema
        tenant_name = await self._require_tenant(session, tenant_id)
        current = await self._select_for_update_status(
            session, tenant_id, document_id
        )
        if current is None:
            raise DocumentNotFoundError(
                document_id=str(document_id), tenant_id=str(tenant_id)
            )
        if current != "PENDING_REVIEW":
            raise InvalidDocumentStateError(
                current_status=current, action="reject"
            )

        result = await session.execute(
            text(
                f"""
                UPDATE {schema}.tenant_documents SET
                    verification_status = 'REJECTED',
                    verified_by_user_id = :actor,
                    verified_at = now(),
                    rejection_reason = :reason,
                    updated_by_user_id = :actor,
                    updated_at = now()
                WHERE tenant_id = :tid AND id = :did
                RETURNING {_READ_COLS}
                """
            ),
            {
                "tid": tenant_id,
                "did": document_id,
                "actor": actor_user_id,
                "reason": rejection_reason,
            },
        )
        row = result.first()
        assert row is not None
        await self._emit(
            session,
            auth=auth,
            request_id=request_id,
            action="REJECT_DOCUMENT",
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            snapshot={
                "resource": "document",
                "document_id": str(document_id),
                "verification_status": "REJECTED",
            },
        )
        return row

    async def delete_if_pending(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        document_id: UUID,
        *,
        actor_user_id: UUID,
        auth: AuthContext | None = None,
        request_id: UUID | None = None,
    ) -> str:
        """Delete a PENDING_REVIEW document row and return its
        ``gcs_object_uri`` so the caller can best-effort delete the GCS
        object. The DB row is authoritative; object cleanup is the
        router's concern and must not fail this operation."""
        schema = get_settings().db_schema
        tenant_name = await self._require_tenant(session, tenant_id)
        locked = (
            await session.execute(
                text(
                    f"""
                    SELECT verification_status, gcs_object_uri
                    FROM {schema}.tenant_documents
                    WHERE tenant_id = :tid AND id = :did
                    FOR UPDATE
                    """
                ),
                {"tid": tenant_id, "did": document_id},
            )
        ).first()
        if locked is None:
            raise DocumentNotFoundError(
                document_id=str(document_id), tenant_id=str(tenant_id)
            )
        if locked.verification_status != "PENDING_REVIEW":
            raise InvalidDocumentStateError(
                current_status=str(locked.verification_status), action="delete"
            )

        await session.execute(
            text(
                f"DELETE FROM {schema}.tenant_documents "
                "WHERE tenant_id = :tid AND id = :did"
            ),
            {"tid": tenant_id, "did": document_id},
        )
        await self._emit(
            session,
            auth=auth,
            request_id=request_id,
            action="DELETE_DOCUMENT",
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            snapshot={
                "resource": "document",
                "document_id": str(document_id),
            },
        )
        return str(locked.gcs_object_uri)

    # ------------------------------------------------------------------
    # Shared audit emission (mirrors OnboardingRepo._emit)
    # ------------------------------------------------------------------

    async def _emit(
        self,
        session: AsyncSession,
        *,
        auth: AuthContext | None,
        request_id: UUID | None,
        action: str,
        tenant_id: UUID,
        tenant_name: str,
        snapshot: dict[str, Any],
    ) -> None:
        if not _emit_args_valid(auth, request_id):
            return
        assert auth is not None and request_id is not None
        await emit_audit_event(
            session,
            auth=auth,
            action=action,
            resource_type="TENANT",
            resource_id=tenant_id,
            resource_label=tenant_name,
            result_type=AuditResultType.SUCCESS,
            details=build_success_details_for_create(snapshot),
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            request_id=request_id,
            route_to_platform=False,
        )
