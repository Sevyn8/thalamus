"""SQLAlchemy ORM model for the ``tenant_tax_registrations`` table.

1:N with ``tenants``. Multi-state GSTIN is
supported: uniqueness is ``(tenant_id, registration_type,
registration_number)`` (not per-type), and ``jurisdiction`` carries the
state / region for a given registration.

``registration_type`` is TEXT validated app-side against the
``tax_registration_type`` ``lookups`` list (PAN/TAN/GSTIN/VAT/EIN);
type-gated length CHECKs (PAN=10, GSTIN=15) live in the DDL.
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, FetchedValue, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from admin_backend.config import get_settings
from admin_backend.db.base import Base


class TenantTaxRegistration(Base):
    """One tax registration for a tenant (1:N)."""

    __tablename__ = "tenant_tax_registrations"
    __table_args__ = {"schema": get_settings().db_schema}

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=FetchedValue()
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)

    registration_type: Mapped[str] = mapped_column(Text, nullable=False)
    registration_number: Mapped[str] = mapped_column(Text, nullable=False)
    jurisdiction: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=FetchedValue()
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=FetchedValue()
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
