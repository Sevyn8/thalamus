"""Tenant onboarding document endpoints.

All routes are tenant-scoped under ``/tenants/{tenant_id}/documents`` and
gated ``ADMIN.TENANTS.CONFIGURE.GLOBAL`` with ``audience="PLATFORM"``
(staff onboarding, D-12), mirroring the gate used by ``routers/v1/onboarding.py``.

Object content never proxies through the backend: upload and download go
direct to GCS via V4 signed URLs minted by the ``SignedUrlGenerator`` seam
(``app.state.gcs_signer``). When storage is not configured
(``gcs_documents_bucket`` unset -> no signer), the URL-minting endpoints
raise ``DocumentStorageUnavailableError`` (503) rather than a raw GCS
exception, mirroring the SendGrid / Auth0-management "unavailable" posture.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from admin_backend.auth.context import AuthContext
from admin_backend.auth.permissions import require
from admin_backend.dependencies import (
    get_auth_context,
    get_tenant_session_dep,
)
from admin_backend.errors import (
    DocumentNotFoundError,
    DocumentStorageUnavailableError,
    FileTooLargeError,
    InvalidContentTypeError,
    TenantNotFoundError,
)
from admin_backend.gcs import (
    ALLOWED_CONTENT_TYPES,
    MAX_FILE_SIZE_BYTES,
    SignedUrlGenerator,
    build_document_object_name,
    build_gs_uri,
    object_name_from_uri,
)
from admin_backend.models.permission import (
    PermissionAction,
    PermissionResource,
    PermissionScope,
)
from admin_backend.models.tenant_module_access import ModuleCode
from admin_backend.repositories.documents import DocumentsRepo
from admin_backend.schemas.document import (
    DocumentDownloadUrlResponse,
    DocumentRead,
    DocumentRejectRequest,
    DocumentsListResponse,
    DocumentUploadUrlRequest,
    DocumentUploadUrlResponse,
)

router = APIRouter(prefix="/tenants", tags=["documents"])

_repo = DocumentsRepo()

_logger = logging.getLogger("admin_backend.documents")


def _gate() -> Any:
    """ADMIN.TENANTS.CONFIGURE.GLOBAL, PLATFORM audience."""
    return require(
        ModuleCode.ADMIN,
        PermissionResource.TENANTS,
        PermissionAction.CONFIGURE,
        PermissionScope.GLOBAL,
        audience="PLATFORM",
    )


def _require_signer(request: Request) -> SignedUrlGenerator:
    """Return the configured GCS signer, or raise 503 if storage is not
    configured (gcs_documents_bucket unset -> no signer constructed)."""
    signer: SignedUrlGenerator | None = getattr(
        request.app.state, "gcs_signer", None
    )
    if signer is None:
        raise DocumentStorageUnavailableError(
            "document storage not configured (gcs_documents_bucket unset)"
        )
    return signer


async def _require_tenant_visible(
    session: AsyncSession, tenant_id: UUID
) -> None:
    if await _repo.tenant_name_or_none(session, tenant_id) is None:
        raise TenantNotFoundError(
            f"Tenant {tenant_id} not visible to this session",
            tenant_id=str(tenant_id),
        )


# ---------------------------------------------------------------------------
# Upload URL (create PENDING_REVIEW row + signed PUT)
# ---------------------------------------------------------------------------


@router.post(
    "/{tenant_id}/documents/upload-url",
    response_model=DocumentUploadUrlResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_document_upload_url(
    tenant_id: UUID,
    body: DocumentUploadUrlRequest,
    request: Request,
    _: None = Depends(_gate()),
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_tenant_session_dep),
) -> Any:
    signer = _require_signer(request)

    if body.content_type not in ALLOWED_CONTENT_TYPES:
        raise InvalidContentTypeError(
            value=body.content_type, allowed=list(ALLOWED_CONTENT_TYPES)
        )
    if body.file_size_bytes > MAX_FILE_SIZE_BYTES:
        raise FileTooLargeError(
            size=body.file_size_bytes, max_size=MAX_FILE_SIZE_BYTES
        )

    object_name = build_document_object_name(tenant_id, body.file_name)
    gcs_object_uri = build_gs_uri(signer.bucket, object_name)

    row = await _repo.create_pending(
        session,
        tenant_id,
        document_type=body.document_type,
        file_name=body.file_name,
        content_type=body.content_type,
        file_size_bytes=body.file_size_bytes,
        gcs_object_uri=gcs_object_uri,
        actor_user_id=auth.user_id,
        auth=auth,
        request_id=request.state.request_id,
    )
    upload_url = signer.generate_upload_url(
        object_name=object_name,
        content_type=body.content_type,
        expiry_seconds=request.app.state.settings.gcs_upload_url_expiry_seconds,
    )
    return DocumentUploadUrlResponse(
        document=DocumentRead.model_validate(row), upload_url=upload_url
    )


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@router.get(
    "/{tenant_id}/documents", response_model=DocumentsListResponse
)
async def list_documents(
    tenant_id: UUID,
    _: None = Depends(_gate()),
    session: AsyncSession = Depends(get_tenant_session_dep),
) -> Any:
    await _require_tenant_visible(session, tenant_id)
    rows = await _repo.list(session, tenant_id)
    return DocumentsListResponse(
        items=[DocumentRead.model_validate(r) for r in rows]
    )


# ---------------------------------------------------------------------------
# Download URL (signed GET, short expiry)
# ---------------------------------------------------------------------------


@router.get(
    "/{tenant_id}/documents/{document_id}/download-url",
    response_model=DocumentDownloadUrlResponse,
)
async def get_document_download_url(
    tenant_id: UUID,
    document_id: UUID,
    request: Request,
    _: None = Depends(_gate()),
    session: AsyncSession = Depends(get_tenant_session_dep),
) -> Any:
    signer = _require_signer(request)
    row = await _repo.get(session, tenant_id, document_id)
    if row is None:
        raise DocumentNotFoundError(
            document_id=str(document_id), tenant_id=str(tenant_id)
        )
    object_name = object_name_from_uri(row.gcs_object_uri, signer.bucket)
    download_url = signer.generate_download_url(
        object_name=object_name,
        expiry_seconds=request.app.state.settings.gcs_download_url_expiry_seconds,
    )
    return DocumentDownloadUrlResponse(download_url=download_url)


# ---------------------------------------------------------------------------
# Verify / reject / delete (verification state machine)
# ---------------------------------------------------------------------------


@router.post(
    "/{tenant_id}/documents/{document_id}/verify",
    response_model=DocumentRead,
)
async def verify_document(
    tenant_id: UUID,
    document_id: UUID,
    request: Request,
    _: None = Depends(_gate()),
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_tenant_session_dep),
) -> Any:
    row = await _repo.verify(
        session,
        tenant_id,
        document_id,
        actor_user_id=auth.user_id,
        auth=auth,
        request_id=request.state.request_id,
    )
    return DocumentRead.model_validate(row)


@router.post(
    "/{tenant_id}/documents/{document_id}/reject",
    response_model=DocumentRead,
)
async def reject_document(
    tenant_id: UUID,
    document_id: UUID,
    body: DocumentRejectRequest,
    request: Request,
    _: None = Depends(_gate()),
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_tenant_session_dep),
) -> Any:
    row = await _repo.reject(
        session,
        tenant_id,
        document_id,
        rejection_reason=body.rejection_reason,
        actor_user_id=auth.user_id,
        auth=auth,
        request_id=request.state.request_id,
    )
    return DocumentRead.model_validate(row)


@router.delete(
    "/{tenant_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(
    tenant_id: UUID,
    document_id: UUID,
    request: Request,
    _: None = Depends(_gate()),
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_tenant_session_dep),
) -> Response:
    gcs_object_uri = await _repo.delete_if_pending(
        session,
        tenant_id,
        document_id,
        actor_user_id=auth.user_id,
        auth=auth,
        request_id=request.state.request_id,
    )
    # Best-effort GCS object cleanup in the same request: the DB row is
    # already gone (authoritative). A signing/storage failure here (or an
    # object that was never uploaded) must NOT fail the delete; log and
    # move on. When storage is unconfigured (signer None) this is a pure
    # row delete (no 503).
    signer: SignedUrlGenerator | None = getattr(
        request.app.state, "gcs_signer", None
    )
    if signer is not None:
        try:
            signer.delete_object(
                object_name=object_name_from_uri(gcs_object_uri, signer.bucket)
            )
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup
            _logger.warning(
                "best-effort GCS object delete failed after document row "
                "delete; object may be orphaned",
                extra={
                    "tenant_id": str(tenant_id),
                    "document_id": str(document_id),
                    "gcs_object_uri": gcs_object_uri,
                    "exception_type": type(exc).__name__,
                },
            )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
