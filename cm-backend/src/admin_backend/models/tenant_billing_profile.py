"""SQLAlchemy ORM model for the ``tenant_billing_profile`` table.

Client onboarding, Slice 1. 1:1 with ``tenants`` (``UNIQUE(tenant_id)``).

``payment_terms`` and ``currency`` are TEXT validated app-side against
the ``payment_terms`` / ``currency`` ``lookups`` lists (flag 4). Email
lowercase + format CHECKs mirror ``tenants``.
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, FetchedValue, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from admin_backend.config import get_settings
from admin_backend.db.base import Base


class TenantBillingProfile(Base):
    """A tenant's billing profile (1:1)."""

    __tablename__ = "tenant_billing_profile"
    __table_args__ = {"schema": get_settings().db_schema}

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=FetchedValue()
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)

    payment_terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    billing_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    billing_contact_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    billing_address: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=FetchedValue()
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=FetchedValue()
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
