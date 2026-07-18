"""``GET /runs`` — the tenant's recent Ingestion Runs (read-only, audit-derived state).

Tenant from the verified token ONLY (no path/query/header tenant input exists). The read goes
through ``repos/runs.py``, which scopes every statement under ``read_session`` (bronze's two-GUC
RLS is the database backstop) plus an explicit tenant predicate on bronze and every joined table.

Run STATE derives from the audit trail (Slice 51a, D117): the repo returns each run's bronze
identity plus its top-precedence terminal audit event; this handler maps that event's
``(stage, outcome)`` to the wire verdict via the SINGLE crosswalk (``verdict_of`` — fail-loud on
an unmapped pair, D118), composes the three independent counts (D119), and renders display names.
Wire<->DB translation lives HERE; the repo speaks DB vocabulary only.

READ-ONLY: this surface never writes bronze (D111). LIST-ONLY this slice: BOUNDED to the newest
``_RUNS_LIST_LIMIT`` runs, no pagination (Slice 51b; the newest-first order is its cursor key).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_core.timestamps import now_utc
from dis_ui_server.auth.scope import ReadScope, require_read_scope
from dis_ui_server.pagination import Boundary, decode_cursor, encode_cursor
from dis_ui_server.repos.runs import list_runs
from dis_ui_server.schemas.runs import (
    CATALOGUE_TABLE,
    PROCESSING,
    RunListResponse,
    RunRow,
    StatusWire,
    WindowWire,
    verdict_of,
)

router = APIRouter()

# Caller-supplied page size (Slice 51b): default = 51a's first-page size; the hard max keeps
# 100 as the ceiling (this endpoint never serves more than today — over-max is clamped, never
# an unbounded query). A cursor walks the full history in bounded pages beyond the first.
_RUNS_PAGE_DEFAULT = 100
_RUNS_PAGE_MAX = 100

# Trailing windows for the Time filter (applied to received_at). now_utc() is the server's UTC
# clock (dis-core); the cutoff is computed once per request.
_WINDOW_DELTA: dict[WindowWire, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _iso(value: datetime) -> str:
    """ISO-8601 with the UTC offset rendered as ``Z`` (the wire convention)."""
    return value.isoformat().replace("+00:00", "Z")


def _verdict(row: Row[Any]) -> StatusWire:
    """The run's verdict: the terminal event's crosswalk mapping (fail-loud), else processing."""
    if row.t_stage is None:  # no terminal-marking audit event -> still in flight / stalled
        return PROCESSING
    return verdict_of(row.t_stage, row.t_outcome)  # KeyError -> 500 on an unmapped pair (D118)


def _accepted(verdict: StatusWire, row: Row[Any]) -> int | None:
    """Rows committed to canonical, path-aware, from the terminal CANONICAL_WRITTEN event (D119).

    Event path (sale/change): ``rows_succeeded``. Catalogue/snapshot path: ``event_rows_written``
    is 0 there, so the real figure is ``hot_rows_upserted + hot_noops`` in ``event_data``. Only a
    succeeded run has an accepted count; quarantined/failed committed nothing; processing is unknown.
    """
    if verdict == "succeeded":
        event_data = row.t_event_data or {}
        if event_data.get("written_to_table") == CATALOGUE_TABLE:
            return int(event_data.get("hot_rows_upserted") or 0) + int(event_data.get("hot_noops") or 0)
        return int(row.t_rows_succeeded) if row.t_rows_succeeded is not None else None
    if verdict in ("quarantined", "failed"):
        return 0
    return None  # processing


def _quarantined(verdict: StatusWire, row: Row[Any]) -> int | None:
    """The ONE quarantine bucket (D119): the QUARANTINED event's held-row count for a quarantined
    run; 0 for succeeded; null for failed (a pure nack is not held) and processing (unknown)."""
    if verdict == "quarantined":
        return int(row.t_row_count) if row.t_row_count is not None else None
    if verdict == "succeeded":
        return 0
    return None  # failed (cell-grain rows_failed is NOT a row count — never surfaced) / processing


def _to_row(row: Row[Any]) -> RunRow:
    verdict = _verdict(row)
    return RunRow(
        id=str(row.id),
        trace_id=str(row.trace_id),
        tenant_id=str(row.tenant_id),  # NOT NULL on bronze — always present
        tenant_name=row.tenant_name,  # Chunk 9: identity_mirror.tenants.name (LEFT JOIN; may be null)
        store_id=str(row.store_id) if row.store_id is not None else None,
        store_name=row.store_name,
        source_id=row.source_id,
        source_name=row.source_name,
        template_id=str(row.template_id) if row.template_id is not None else None,
        template_name=row.template_name,
        method=row.dis_channel,  # passthrough (CHECK-constrained to the wire vocab)
        status=verdict,  # the audit-derived verdict (wire key stays 'status', D117)
        mapping_version=row.t_mapping_version,  # from the terminal audit event (D117)
        seen_before=bool(row.seen_before),  # recorded duplicate outcome (D119, criterion 5)
        source_payload_id=row.source_payload_id,
        file_name=row.original_filename,  # null on pre-Slice-51a runs (D120)
        input_row_count=row.row_count,  # bronze total (worker DuckDB preflight)
        accepted=_accepted(verdict, row),
        quarantined=_quarantined(verdict, row),
        received_at=_iso(row.received_at),
        published_at=_iso(row.published_at) if row.published_at is not None else None,
        completed_at=_iso(row.t_completed_at) if row.t_completed_at is not None else None,
    )


@router.get("/runs")
async def list_ingestion_runs(
    request: Request,
    scope: Annotated[ReadScope, Depends(require_read_scope)],
    status: Annotated[StatusWire | None, Query()] = None,
    window: Annotated[WindowWire | None, Query()] = None,
    limit: Annotated[int, Query(ge=1)] = _RUNS_PAGE_DEFAULT,
    cursor: Annotated[str | None, Query()] = None,
) -> RunListResponse:
    """One keyset page of recent ingress runs (newest first). TENANT sees its own; PLATFORM
    (user_type=PLATFORM + dis:ops) sees cross-tenant. ``status``/``window`` filter the
    audit-derived verdict; ``limit`` is the page size (clamped to the hard max, never
    unbounded); ``cursor`` walks older pages and is valid only within its issuing filter set
    (a mismatch is a 422 ``invalid_cursor``, never a silent wrong page). ``next_cursor`` in the
    body is null when no more runs remain (Slice 51b, D124)."""
    engine: AsyncEngine = request.app.state.engine
    page_size = min(limit, _RUNS_PAGE_MAX)  # clamp over-max; <1 / non-int already 422 (Query ge=1)
    cutoff = now_utc() - _WINDOW_DELTA[window] if window is not None else None
    # Decode within the CURRENT filter set — a cursor from a different status/window is rejected
    # (fail-loud) rather than reinterpreted (decode_cursor raises InvalidCursorError -> 422).
    after = decode_cursor(cursor, status=status, window=window) if cursor is not None else None
    # Over-fetch by one (repo asks for page_size + 1): an extra row means a next page exists.
    runs = await list_runs(engine, scope, limit=page_size, status=status, window_cutoff=cutoff, after=after)
    page = runs[:page_size]
    next_cursor: str | None = None
    if len(runs) > page_size:
        last = page[-1]
        next_cursor = encode_cursor(
            Boundary(received_at=last.received_at, id=last.id), status=status, window=window
        )
    return RunListResponse(items=[_to_row(run) for run in page], next_cursor=next_cursor)
