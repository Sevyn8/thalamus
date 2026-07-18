"""Connector-health emit (D116) with an optional metadata hint.

Mirrors csv-ingest-worker's ``connector_health`` upserts EXACTLY (same table, same
``ON CONFLICT (tenant_id, source_id)`` semantics, same "never null a column this path is
not stamping" rule) but adds an optional ``metadata`` JSONB the CSV worker's variant does
not carry — e.g. ``{"dropped_count": N}`` for the health surface. Kept in the SDK so the
connector owns its health-write shape without changing the CSV worker; ``metadata`` is
merged with ``COALESCE(EXCLUDED.metadata, ...)`` so passing ``None`` preserves any prior
value.

Every statement runs on a ``dis-rls`` ``rls_session`` connection under the trigger's
tenant (hard rules 1 & 12); the WITH CHECK pins the write to that tenant. The caller keeps
the fire-and-forget posture (a health-emit failure never blocks ingest, D116).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from dis_core.timestamps import now_utc

STATUS_HEALTHY = "healthy"
STATUS_STALE = "stale"


def _metadata_json(metadata: dict[str, Any] | None) -> str | None:
    """Serialize the metadata dict for the ``CAST(:metadata AS JSONB)`` bind, or None."""
    return json.dumps(metadata) if metadata is not None else None


async def upsert_health_seen(
    conn: AsyncConnection,
    *,
    tenant_id: UUID,
    source_id: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """A successful arrival: stamp ``last_seen_at`` + ``status='healthy'`` (idempotent).

    ``metadata`` (e.g. ``{"dropped_count": N}``) is merged, not overwritten: a None keeps
    the stored value via COALESCE, so a healthy re-run never clears a prior hint.
    """
    await conn.execute(
        text(
            "INSERT INTO telemetry.connector_health "
            "(tenant_id, source_id, last_seen_at, status, metadata, updated_at) "
            "VALUES (:tenant_id, :source_id, :now, :status, CAST(:metadata AS JSONB), :now) "
            "ON CONFLICT (tenant_id, source_id) DO UPDATE SET "
            "last_seen_at = EXCLUDED.last_seen_at, "
            "status = EXCLUDED.status, "
            "metadata = COALESCE(EXCLUDED.metadata, telemetry.connector_health.metadata), "
            "updated_at = EXCLUDED.updated_at"
        ),
        {
            "tenant_id": tenant_id,
            "source_id": source_id,
            "now": now_utc(),
            "status": STATUS_HEALTHY,
            "metadata": _metadata_json(metadata),
        },
    )


async def upsert_health_error(
    conn: AsyncConnection,
    *,
    tenant_id: UUID,
    source_id: str,
    detail: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """A failed run: stamp ``last_error_at`` + ``last_error_detail`` + ``status='stale'``.

    Keeps ``last_seen_at`` (a prior success stays visible); ``detail`` is a coarse non-PII
    reason code (never payload). ``metadata`` follows the same COALESCE-merge rule.
    """
    await conn.execute(
        text(
            "INSERT INTO telemetry.connector_health "
            "(tenant_id, source_id, last_error_at, last_error_detail, status, metadata, updated_at) "
            "VALUES (:tenant_id, :source_id, :now, :detail, :status, CAST(:metadata AS JSONB), :now) "
            "ON CONFLICT (tenant_id, source_id) DO UPDATE SET "
            "last_error_at = EXCLUDED.last_error_at, "
            "last_error_detail = EXCLUDED.last_error_detail, "
            "status = EXCLUDED.status, "
            "metadata = COALESCE(EXCLUDED.metadata, telemetry.connector_health.metadata), "
            "updated_at = EXCLUDED.updated_at"
        ),
        {
            "tenant_id": tenant_id,
            "source_id": source_id,
            "now": now_utc(),
            "detail": detail,
            "status": STATUS_STALE,
            "metadata": _metadata_json(metadata),
        },
    )
