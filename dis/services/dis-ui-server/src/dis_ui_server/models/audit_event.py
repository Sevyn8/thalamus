"""``audit.events`` - the end-to-end pipeline audit trail (read-only here).

A faithful read mirror of the columns the ``GET /audit`` list serves. dis-ui-server
NEVER writes this table via SQL - emission is ``libs/dis-audit`` fire-and-forget from
every service (root CLAUDE.md hard rule 11); this model is typed read metadata only.

RLS is the two-GUC OUTLIER (Slice 17b / D91): the ``rls_audit_events_tenant`` policy is
USING-only - ``tenant_id = app.tenant_id OR tenant_id IS NULL OR app.user_type='PLATFORM'``
- with NO WITH CHECK (the UI never writes). The per-tenant scope rides ``rls_session``;
the explicit ``WHERE tenant_id`` predicate in ``repos/audit.py`` is defense-in-depth AND
- because ``tenant_id IS NULL`` system rows satisfy the USING branch for every tenant -
the thing that keeps a TENANT read from surfacing other-tenant/system rows (intended).

``auth_principal`` and ``client_ip`` are DELIBERATELY NOT MIRRORED: they are caller-context
PII (root CLAUDE.md logging rule) and never reach the tenant wire, so the read must not be
able to select them. The columns not read by the list (``event_date``, ``service_version``,
``data_ingress_event_id``, ``row_offset``, ``_loaded_at``) are likewise omitted, per the
minimal-mirror precedent of the quarantine models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dis_ui_server.db import Base


class AuditEvent(Base):
    """One audit event (faithful read mirror of the served columns of ``audit.events``)."""

    __tablename__ = "events"
    __table_args__ = {"schema": "audit"}

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trace_id: Mapped[UUID] = mapped_column(Uuid)
    prior_trace_id: Mapped[UUID | None] = mapped_column(Uuid)  # NULL on non-duplicate rows
    tenant_id: Mapped[UUID | None] = mapped_column(Uuid)  # NULL for system/pre-auth events
    # The bronze run this event belongs to (Slice 51a: the runs-surface verdict/counts join key,
    # partial index ix_audit_events_data_ingress_event). NULL for events outside the ingress
    # lifecycle. Read-only mirror addition; no DDL (the column exists live).
    data_ingress_event_id: Mapped[UUID | None] = mapped_column(Uuid)
    service_name: Mapped[str] = mapped_column(String(64))
    stage: Mapped[str] = mapped_column(String(64))
    # CHECK ck_audit_events_event_scope_vocab: INGRESS_EVENT | ROW.
    event_scope: Mapped[str] = mapped_column(String(32))
    # CHECK ck_audit_events_outcome_vocab (6 members); translated to the wire taxonomy in
    # schemas/audit.py - the single crosswalk, never re-derived.
    outcome: Mapped[str] = mapped_column(String(32))
    row_count: Mapped[int | None] = mapped_column(Integer)
    rows_succeeded: Mapped[int | None] = mapped_column(Integer)
    rows_failed: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    mapping_version_id: Mapped[int | None] = mapped_column(BigInteger)  # NULL pre-lookup
    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_message: Mapped[str | None] = mapped_column(String(2048))
    event_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
