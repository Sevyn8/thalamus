"""Pydantic schemas for tenant onboarding documents (Slice 3).

Reads use ``from_attributes=True`` and hide the internal storage ref
(``gcs_object_uri``) and audit-actor columns per the D-28 convention;
requests use ``extra="forbid"``.

``document_type`` is a plain string validated app-side against the
active ``document_type`` ``core.lookups`` rows in ``DocumentsRepo``
(a Pydantic validator would raise the Pydantic 422 envelope, not the
project envelope). ``content_type`` and ``file_size_bytes`` are validated
in the router against the allowlist / max-size so the project envelope
names the field.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    document_type: str
    file_name: str | None
    content_type: str | None
    file_size_bytes: int | None
    verification_status: str
    verified_at: datetime | None
    rejection_reason: str | None
    created_at: datetime


class DocumentUploadUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: str = Field(min_length=1)
    file_name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1)
    file_size_bytes: int = Field(gt=0)


class DocumentUploadUrlResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: DocumentRead
    upload_url: str


class DocumentsListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DocumentRead]


class DocumentDownloadUrlResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    download_url: str


class DocumentRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rejection_reason: str = Field(min_length=1, max_length=2000)
