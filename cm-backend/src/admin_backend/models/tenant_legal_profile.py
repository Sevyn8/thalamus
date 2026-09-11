"""SQLAlchemy ORM model for the ``tenant_legal_profile`` table.

1:1 with ``tenants`` (``UNIQUE(tenant_id)``).
Mirrors the ``tenants`` conventions: ``uuidv7()`` PK via
``FetchedValue()``, ``created_at`` / ``updated_at`` server defaults,
Pattern (a) nullable audit-actor FK columns to ``platform_users``
(DB enforces the FK; not modelled at the SA layer per the v0 convention).

``entity_type`` is TEXT validated app-side against the ``entity_type``
``lookups`` list (flag 4, option b); no PG enum.
"""
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, FetchedValue, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from admin_backend.config import get_settings
from admin_backend.db.base import Base


class TenantLegalProfile(Base):
    """A tenant's legal / incorporation profile (1:1)."""

    __tablename__ = "tenant_legal_profile"
    __table_args__ = {"schema": get_settings().db_schema}

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=FetchedValue()
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)

    legal_entity_name: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    registration_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    incorporation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    registered_address: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=FetchedValue()
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=FetchedValue()
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
