"""``GET /connector-health`` — the tenant's connectors with health (read-only, D116).

Tenant from the verified token ONLY (no path/query/header tenant input). The read goes through
``repos/connector_health.py`` (``read_session``, two-GUC RLS + a defense-in-depth predicate),
which drives from ``config.sources`` and LEFT JOINs the worker-written ``telemetry.connector_health``
plus a bronze last-arrival. Wire translation lives HERE (mirroring ``runs``): the ``last_seen_at``
COALESCE, the ISO rendering, and the derived-on-read ``status`` (``schemas.connector_health``).

READ-ONLY: this surface never writes the health table.
LIST-ONLY: the tenant's connector registry is bounded (one row per config.sources entry), no paging.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_core.timestamps import now_utc
from dis_ui_server.auth.scope import ReadScope, require_read_scope
from dis_ui_server.repos.connector_health import list_connector_health
from dis_ui_server.schemas.connector_health import (
    ConnectorHealthListResponse,
    ConnectorHealthRow,
    derive_status,
)

router = APIRouter()


def _iso(value: datetime | None) -> str | None:
    """ISO-8601 with the UTC offset rendered as ``Z`` (the wire convention); None passes through."""
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


def _to_row(row: Row[Any], *, now: datetime) -> ConnectorHealthRow:
    # COALESCE the worker's last_seen with the bronze last-arrival: an active connector
    # shows freshness even before the worker has emitted a health row.
    effective_last_seen: datetime | None = row.health_last_seen_at or row.bronze_last_seen
    status = derive_status(
        effective_last_seen=effective_last_seen,
        auth_expires_at=row.auth_expires_at,
        rate_limit_state=row.rate_limit_state,
        now=now,
    )
    return ConnectorHealthRow(
        tenant_id=str(row.tenant_id),  # NOT NULL on config.sources — always present
        tenant_name=row.tenant_name,  # Chunk 9: identity_mirror.tenants.name (LEFT JOIN; may be null)
        source_id=row.source_id,
        display_name=row.display_name,
        channel=row.channel,  # passthrough (CHECK-constrained to the wire vocab; nullable)
        heartbeat_label=row.heartbeat_label,  # config.sources.schedule (display cadence)
        status=status,
        last_seen_at=_iso(effective_last_seen),
        last_error_at=_iso(row.last_error_at),
        last_error_detail=row.last_error_detail,
        auth_expires_at=_iso(row.auth_expires_at),
        rate_limit_state=row.rate_limit_state,
        missed_intervals=row.missed_intervals,
    )


@router.get("/connector-health")
async def list_connectors(
    request: Request,
    scope: Annotated[ReadScope, Depends(require_read_scope)],
) -> ConnectorHealthListResponse:
    """The tenant's connectors with derived health. TENANT sees its own; PLATFORM
    (user_type=PLATFORM + dis:ops) sees cross-tenant."""
    engine: AsyncEngine = request.app.state.engine
    now = now_utc()
    rows = await list_connector_health(engine, scope)
    return ConnectorHealthListResponse(items=[_to_row(row, now=now) for row in rows])
