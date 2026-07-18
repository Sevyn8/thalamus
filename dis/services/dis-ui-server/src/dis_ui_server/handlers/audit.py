"""``GET /audit`` - the tenant's recent pipeline audit events (read-only).

Tenant from the verified token ONLY (no path/query/header tenant input exists). The read
goes through ``repos/audit.py``, which scopes every statement under ``read_session`` (the
``audit.events`` two-GUC RLS policy is the database backstop) plus an explicit tenant
predicate that, for a TENANT scope, also excludes ``tenant_id IS NULL`` system rows. Wire
<->DB translation lives HERE (the single outcome crosswalk in ``schemas/audit.py``, the
window->cutoff, the trace_id parse); the repo speaks DB vocabulary only.

LIST-ONLY this slice: BOUNDED to the newest ``_AUDIT_LIST_LIMIT`` events, no pagination
(audit is high-volume). A per-trace drill-in (``GET /audit/{trace_id}``) is a later slice.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_core.errors import ResourceNotFoundError
from dis_core.timestamps import now_utc
from dis_ui_server.auth.scope import ReadScope, require_read_scope
from dis_ui_server.repos.audit import list_events
from dis_ui_server.schemas.audit import (
    AuditEventListResponse,
    AuditEventRow,
    OutcomeWire,
    WindowWire,
    outcome_db_values_for,
    outcome_to_wire,
)

router = APIRouter()

# The bounded newest-N for the list (no pagination this slice; audit is high-volume).
_AUDIT_LIST_LIMIT = 100

# Trailing windows for the Time filter (applied to event_timestamp). now_utc() is the
# server's UTC clock (dis-core); the cutoff is computed once per request.
_WINDOW_DELTA: dict[WindowWire, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _iso(value: datetime) -> str:
    """ISO-8601 with the UTC offset rendered as ``Z`` (the wire convention)."""
    return value.isoformat().replace("+00:00", "Z")


def _parse_trace_id(trace_id: str) -> UUID:
    """Parse the ``trace_id`` filter as a UUID; a malformed value is a clean 404.

    404 (not 422) keeps the no-existence-oracle posture: a malformed trace and an unknown
    trace both surface as "no such trace for you", never an oracle on trace shape.
    """
    try:
        return UUID(trace_id)
    except ValueError as exc:
        raise ResourceNotFoundError(
            f"audit trace_id {trace_id!r} is not a valid trace identifier",
            resource="audit_trace",
            identifier=trace_id,
        ) from exc


def _to_row(row: Row[Any]) -> AuditEventRow:
    return AuditEventRow(
        id=str(row.id),
        trace_id=str(row.trace_id),
        tenant_id=str(row.tenant_id) if row.tenant_id is not None else None,  # NULL on system rows
        tenant_name=row.tenant_name,  # Chunk 9: null for system rows (tenant_id NULL) / unmirrored
        prior_trace_id=str(row.prior_trace_id) if row.prior_trace_id is not None else None,
        event_timestamp=_iso(row.event_timestamp),
        service_name=row.service_name,
        stage=row.stage,
        event_scope=row.event_scope,
        outcome=outcome_to_wire(row.outcome),  # forward crosswalk (fail-loud on unknown)
        row_count=row.row_count,
        rows_succeeded=row.rows_succeeded,
        rows_failed=row.rows_failed,
        duration_ms=row.duration_ms,
        mapping_version=row.mapping_version_id,  # null for pre-lookup stages
        failure_code=row.failure_code,
        failure_message=row.failure_message,
        event_data=row.event_data,
    )


@router.get("/audit")
async def list_audit_events(
    request: Request,
    scope: Annotated[ReadScope, Depends(require_read_scope)],
    trace_id: Annotated[str | None, Query()] = None,
    outcome: Annotated[OutcomeWire | None, Query()] = None,
    window: Annotated[WindowWire | None, Query()] = None,
) -> AuditEventListResponse:
    """Recent audit events (newest first), bounded. TENANT sees its own (system rows
    excluded); PLATFORM (user_type=PLATFORM + dis:ops) sees cross-tenant, incl. system rows."""
    engine: AsyncEngine = request.app.state.engine
    # Translate wire filters -> DB vocabulary; the repo is DB-only.
    parsed_trace = _parse_trace_id(trace_id) if trace_id is not None else None
    outcomes = outcome_db_values_for(outcome) if outcome is not None else None
    cutoff = now_utc() - _WINDOW_DELTA[window] if window is not None else None
    events = await list_events(
        engine,
        scope,
        limit=_AUDIT_LIST_LIMIT,
        trace_id=parsed_trace,
        outcomes=outcomes,
        window_cutoff=cutoff,
    )
    return AuditEventListResponse(items=[_to_row(event) for event in events])
