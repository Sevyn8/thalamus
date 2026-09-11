"""``bronze.data_ingress_events`` - the ingress-run metadata (READ-ONLY here).

A faithful read mirror of the columns the ``GET /runs`` list serves. dis-ui-server reads
bronze read-only for the runs surface; the STREAMING CONSUMER + RECEIVERS remain
bronze's SOLE writers — dis-ui-server must never write bronze tables. This model is
typed read metadata only; the runs repo builds SELECT-only statements and never an
INSERT/UPDATE/DELETE.

RLS is the standard two-GUC policy: ``tenant_isolation`` = ``USING (tenant_id =
app.tenant_id OR app.user_type='PLATFORM')`` + ``WITH CHECK`` tenant-pin — the same READ
behaviour as ``quarantine.*`` (a TENANT sees its own, PLATFORM sees all). The per-tenant scope
rides ``read_session``; the explicit ``WHERE tenant_id`` predicate in ``repos/runs.py`` is
defense-in-depth. bronze.tenant_id is NOT NULL, so — unlike ``audit.events`` — there are no
system/null rows to consider.

``auth_principal`` / ``client_ip`` / ``user_agent`` (caller-context PII) and ``gcs_uri`` (the
payload location) are DELIBERATELY NOT MIRRORED: they never reach the tenant wire, so the read
must not be able to select them. Payload columns not needed by the list (``payload_size_bytes``,
``payload_sha256``, ``content_type``) are likewise omitted (the minimal-mirror precedent of the
quarantine / audit models).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from dis_ui_server.db import Base


class DataIngressEvent(Base):
    """One ingress run (faithful read mirror of the served columns of ``bronze.data_ingress_events``)."""

    __tablename__ = "data_ingress_events"
    __table_args__ = {"schema": "bronze"}

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)  # NOT NULL (no system rows)
    store_id: Mapped[UUID | None] = mapped_column(Uuid)  # NULL when store is deferred to the consumer
    source_id: Mapped[str] = mapped_column(String(128))
    # CHECK ck_bdie_dis_channel_vocab: csv_upload | api | csv_erp | reverse_api. The ingress
    # channel — the "Method" column; passed through to the wire (already wire-friendly).
    dis_channel: Mapped[str] = mapped_column(String(32))
    trace_id: Mapped[UUID] = mapped_column(Uuid)
    source_payload_id: Mapped[str | None] = mapped_column(String(256))  # File/event ref
    row_count: Mapped[int | None] = mapped_column(Integer)  # total rows (worker DuckDB preflight)
    mapping_version_id: Mapped[int | None] = mapped_column(BigInteger)
    # replay-lineage; NULL on older runs predating this column
    template_id: Mapped[UUID | None] = mapped_column(Uuid)
    # The uploaded file's original name; NULL on pre-51a runs (no backfill).
    original_filename: Mapped[str | None] = mapped_column(String(512))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # CHECK ck_bdie_processing_status_vocab (5 members). INGRESS-ONLY signal —
    # the runs surface derives its verdict from audit.events, NOT from this column (the
    # declared "consumer advances it to PROCESSED/QUARANTINED/FAILED" design is superseded).
    processing_status: Mapped[str] = mapped_column(String(32))
    # last_updated_at is intentionally NOT mirrored: it was an ingress-only
    # signal dropped from the runs response; nothing else reads it, so the read must not select
    # it. completed_at (the terminal audit event) is the meaningful "finished" timestamp.
