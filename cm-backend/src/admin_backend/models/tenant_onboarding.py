"""SQLAlchemy ORM model for the ``tenant_onboarding`` table.

Client onboarding, Slice 1. 1:1 with ``tenants`` (``UNIQUE(tenant_id)``).
Holds wizard state: ``current_step``, per-section ``section_status``
(JSONB map of section-key -> status-code; wizard section endpoints are
out of scope this slice), and the completion stamp
(``completed_by_user_id`` FK to ``platform_users`` + ``completed_at``,
paired by a DDL CHECK).

The initial row is provisioned atomically by ``TenantsRepo.create``
(flag 5b); ``POST /tenants/{id}/complete-onboarding`` stamps the
completion fields when the tenant moves ONBOARDING -> TRIAL.
"""
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, FetchedValue, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from admin_backend.config import get_settings
from admin_backend.db.base import Base


class TenantOnboarding(Base):
    """A tenant's onboarding wizard state (1:1)."""

    __tablename__ = "tenant_onboarding"
    __table_args__ = {"schema": get_settings().db_schema}

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=FetchedValue()
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)

    current_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_status: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=FetchedValue()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=FetchedValue()
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=FetchedValue()
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
