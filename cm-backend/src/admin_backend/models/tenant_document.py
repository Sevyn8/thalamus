"""SQLAlchemy ORM model for the ``tenant_documents`` table.

Client onboarding, Slice 1. 1:N with ``tenants``. Holds GCS object
references only; no upload logic in this slice.

``document_type`` is TEXT validated app-side against the
``document_type`` ``lookups`` list. ``gcs_object_uri`` is the storage
reference (non-empty CHECK in the DDL); the object itself is written by
a later slice.
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, FetchedValue, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from admin_backend.config import get_settings
from admin_backend.db.base import Base


class TenantDocument(Base):
    """One document reference for a tenant (1:N)."""

    __tablename__ = "tenant_documents"
    __table_args__ = {"schema": get_settings().db_schema}

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=FetchedValue()
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)

    document_type: Mapped[str] = mapped_column(Text, nullable=False)
    gcs_object_uri: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=FetchedValue()
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=FetchedValue()
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
