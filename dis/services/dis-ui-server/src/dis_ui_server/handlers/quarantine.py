"""The Quarantine console endpoints - two tenant-facing reads.

``GET /quarantine`` - the tenant's held items (rows ∪ chunks), newest first, with
four server-side filters (Source, Error type, Status, Time) and the header's
filter-INDEPENDENT open count. ``GET /quarantine/{item_id}`` - one held item in
full, addressed by a type-tagged id (``"row:<uuid>"``/``"chunk:<uuid>"``) so detail
dispatch is unambiguous across the two tables.

Tenant from the verified token ONLY (no path/query/header tenant input exists, so
none can be honoured); the reads go through ``repos/quarantine.py``, which scopes
every statement under ``rls_session`` (the ``quarantine.*`` RLS policy is the
database backstop) plus an explicit tenant predicate. Wire<->DB translation lives
here (the single crosswalk in ``schemas/quarantine.py``); the repo speaks DB
vocabulary only.

Honest semantics: Status ``resolved`` returns empty today because no row can be
resolved; the value stays in the filter, forward-compatible.
The ORIGINAL PAYLOAD is DEFERRED (build-cost, not PII - CSV beta carries none): the
field is present and returns ``null`` until a fast-follow wires the GCS read.
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
from dis_ui_server.repos.quarantine import count_open, get_held_item, list_held_items
from dis_ui_server.schemas.quarantine import (
    Kind,
    QuarantineDetail,
    QuarantineFailure,
    QuarantineListResponse,
    QuarantineListRow,
    StageWire,
    StatusWire,
    WindowWire,
    stage_db_values_for,
    stage_to_wire,
    status_db_values_for,
    status_to_wire,
)

router = APIRouter()

# Trailing windows for the Time filter (applied to quarantined_at). now_utc() is the
# server's UTC clock (dis-core); the cutoff is computed once per request.
_WINDOW_DELTA: dict[WindowWire, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _iso(value: datetime) -> str:
    """ISO-8601 with the UTC offset rendered as ``Z`` (the wire convention)."""
    return value.isoformat().replace("+00:00", "Z")


def _parse_item_id(item_id: str) -> tuple[Kind, UUID]:
    """Split a type-tagged id into (kind, uuid); a malformed/unknown tag is a clean 404.

    Returning 404 (not 422) keeps detail uniform: an unknown item and a malformed
    handle are both "no such item for you", with no existence oracle.
    """
    kind_raw, sep, raw = item_id.partition(":")
    if sep != ":" or kind_raw not in ("row", "chunk"):
        raise ResourceNotFoundError(
            f"quarantine item id {item_id!r} is not a 'row:<uuid>'/'chunk:<uuid>' handle",
            resource="quarantine_item",
            identifier=item_id,
        )
    try:
        item_uuid = UUID(raw)
    except ValueError as exc:
        raise ResourceNotFoundError(
            f"quarantine item id {item_id!r} carries a malformed uuid",
            resource="quarantine_item",
            identifier=item_id,
        ) from exc
    kind: Kind = "row" if kind_raw == "row" else "chunk"
    return kind, item_uuid


def _compose_context(stage_wire: StageWire, failure_context: dict[str, Any] | None) -> str:
    """The fuller Context string, composed from the row's own failure fields (no second store).

    Chunk failures carry a ``failure_message``; row failures carry a ``failures[]``
    list of column/check/reason. Either way the stage prefixes it, reproducing the
    screen's "canonical-shape: column price failed numeric cast" shape.
    """
    if not failure_context:
        return stage_wire
    message = failure_context.get("failure_message")
    if isinstance(message, str) and message:
        return f"{stage_wire}: {message}"
    failures = failure_context.get("failures")
    if isinstance(failures, list) and failures:
        parts: list[str] = []
        for failure in failures:
            if not isinstance(failure, dict):
                continue
            segment = ", ".join(
                str(failure[key]) for key in ("column", "check", "reason") if failure.get(key)
            )
            if segment:
                parts.append(segment)
        if parts:
            return f"{stage_wire}: " + "; ".join(parts)
    return stage_wire


def _to_failures(failure_context: dict[str, Any] | None) -> list[QuarantineFailure]:
    """Structured per-failure detail, built defensively from failure_context.

    Reads the SAME ``failures[]`` the flattened ``error_context`` string reads (so the
    two are consistent), but returns the typed shape. A non-dict element or one missing
    ``check``/``reason`` (the only required fields) is skipped — never a 500. Absent
    optional keys stay absent → the model's None defaults (AC1: omitted, not fabricated).
    Detail-only; the list never selects failure_context.
    """
    if not failure_context:
        return []
    raw = failure_context.get("failures")
    if not isinstance(raw, list):
        return []
    out: list[QuarantineFailure] = []
    for element in raw:
        if not isinstance(element, dict):
            continue
        check = element.get("check")
        reason = element.get("reason")
        if not isinstance(check, str) or not isinstance(reason, str):
            continue
        out.append(
            QuarantineFailure(
                check=check,
                reason=reason,
                column=element.get("column"),
                row_index=element.get("row_index"),
                value=element.get("value"),
                source_column=element.get("source_column"),
                expected_format=element.get("expected_format"),
                transform_index=element.get("transform_index"),
            )
        )
    return out


def _store_id_str(row: Row[Any]) -> str | None:
    """The held item's store_id as a wire string, or None when unset/unmirrored (52b)."""
    return str(row.store_id) if row.store_id is not None else None


def _to_list_row(row: Row[Any]) -> QuarantineListRow:
    return QuarantineListRow(
        id=f"{row.kind}:{row.id}",
        kind=row.kind,
        trace_id=str(row.trace_id),
        tenant_id=str(row.tenant_id),  # NOT NULL on quarantine tables — always present
        tenant_name=row.tenant_name,  # Chunk 9: identity_mirror.tenants.name (LEFT JOIN; may be null)
        source_id=row.source_id,
        source=row.source_id,  # display fallback: raw source_id (no registry - fast-follow)
        store_id=_store_id_str(row),  # 52b
        store_name=row.store_name,  # 52b: from the inline stores join; null when store_id null
        error_reason=row.failure_reason,
        failure_stage=stage_to_wire(row.failure_stage),
        failed_at=_iso(row.quarantined_at),
        status=status_to_wire(row.status),
    )


def _to_detail(row: Row[Any]) -> QuarantineDetail:
    stage_wire = stage_to_wire(row.failure_stage)
    return QuarantineDetail(
        id=f"{row.kind}:{row.id}",
        kind=row.kind,
        trace_id=str(row.trace_id),
        tenant_name=row.tenant_name,  # Chunk 9: identity_mirror.tenants.name (LEFT JOIN; may be null)
        source=row.source_id,
        store_id=_store_id_str(row),  # 52b
        store_name=row.store_name,  # 52b: from the inline stores join; null when store_id null
        failed_at=_iso(row.quarantined_at),
        mapping_version=row.mapping_version_id,  # null for pre-lookup chunk failures
        error_reason=row.failure_reason,
        failure_stage=stage_wire,
        error_context=_compose_context(stage_wire, row.failure_context),  # UNCHANGED (52b keeps it)
        failures=_to_failures(row.failure_context),  # 52b: structured, alongside error_context
        original_payload=None,  # DEFERRED (build-cost fast-follow); contract-stable null
        chain_depth=0,  # no parent_trace_id lineage is tracked yet
    )


@router.get("/quarantine")
async def list_quarantine(
    request: Request,
    scope: Annotated[ReadScope, Depends(require_read_scope)],
    source: Annotated[str | None, Query()] = None,
    error_type: Annotated[StageWire | None, Query()] = None,
    status: Annotated[StatusWire | None, Query()] = None,
    window: Annotated[WindowWire | None, Query()] = None,
) -> QuarantineListResponse:
    """Held items (newest first) + filter-independent open count. TENANT sees its own;
    PLATFORM (user_type=PLATFORM + dis:ops) sees cross-tenant."""
    engine: AsyncEngine = request.app.state.engine
    # Translate wire filters -> DB vocabulary via the single crosswalk; the repo is DB-only.
    stages = stage_db_values_for(error_type) if error_type is not None else None
    statuses = status_db_values_for(status) if status is not None else None
    cutoff = now_utc() - _WINDOW_DELTA[window] if window is not None else None
    items = await list_held_items(
        engine, scope, source=source, stages=stages, statuses=statuses, cutoff=cutoff
    )
    open_count = await count_open(engine, scope)
    return QuarantineListResponse(items=[_to_list_row(item) for item in items], open_count=open_count)


@router.get("/quarantine/{item_id}")
async def get_quarantine_item(
    request: Request,
    scope: Annotated[ReadScope, Depends(require_read_scope)],
    item_id: str,
) -> QuarantineDetail:
    """One held item in full by its type-tagged id; unknown/out-of-scope id -> 404."""
    engine: AsyncEngine = request.app.state.engine
    kind, item_uuid = _parse_item_id(item_id)
    row = await get_held_item(engine, scope, kind=kind, item_id=item_uuid)
    return _to_detail(row)
