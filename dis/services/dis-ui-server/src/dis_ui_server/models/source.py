"""``config.sources`` — the per-source registry entity (Phase A, D112).

The first writable table dis-ui-server owns in the shared DB. Written via
``write_session`` (POST /sources) and the 0013 backfill; read via ``read_session``
(GET /sources). RLS is two-GUC (``USING tenant OR PLATFORM``, ``WITH CHECK`` tenant-pin
— the write backstop). One row per ``(tenant_id, source_id)``. STANDALONE in Phase A:
no FK from ``config.source_mappings.source_id`` to here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dis_ui_server.db import Base


class Source(Base):
    """One registered source (faithful mirror of ``config.sources``)."""

    __tablename__ = "sources"
    __table_args__ = {"schema": "config"}

    # Composite PK (tenant_id, source_id).
    tenant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(256))
    # CHECK ck_config_sources_channel_vocab (dis_channel vocab); NULL when unknown.
    channel: Mapped[str | None] = mapped_column(String(32))
    store_id: Mapped[str | None] = mapped_column(String(128))
    schedule: Mapped[str | None] = mapped_column(String(128))
    # CHECK ck_config_sources_status_vocab: active | paused | disabled.
    status: Mapped[str] = mapped_column(String(32))
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
