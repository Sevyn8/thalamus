"""``audit.events`` reads - the audit event log's data access (GET /audit).

``audit.events`` is RLS ON + FORCE with the two-GUC OUTLIER policy (Slice 17b / D91):
``rls_audit_events_tenant`` is USING-only - ``tenant_id = app.tenant_id OR tenant_id IS
NULL OR app.user_type='PLATFORM'`` - with no WITH CHECK (the UI never writes). The per-tenant
scope is the DATABASE's guarantee, applied by ``read_session``. The explicit ``WHERE
tenant_id`` predicate here is defense-in-depth (the 14b D41 pattern) AND, because the USING
branch admits ``tenant_id IS NULL`` system rows to EVERY tenant, it is what keeps a TENANT
read from surfacing those system/other-tenant rows - the equality predicate excludes NULL.
Do NOT relax it (the audit-specific isolation guard; criterion pinned in the integration test).

Reads execute CORE-STYLE on the ``read_session`` connection (service CLAUDE.md durable
invariant); never an ``AsyncSession``. This module speaks DB vocabulary only - wire<->DB
translation (the outcome crosswalk, window->cutoff, trace_id parse, ISO rendering) lives in
the handler. The list is BOUNDED newest-first (audit is high-volume; no pagination this
slice) and rides the ``ix_audit_events_tenant_time`` index. ``scope`` MUST come from the
verified token (``require_read_scope``); this module trusts its caller on that.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Row, select
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_core.errors import TenantScopeError
from dis_ui_server.auth.scope import ReadScope
from dis_ui_server.db import read_session
from dis_ui_server.models import AuditEvent, TenantRow

# The list projection - the served columns only (PII columns are not on the model, so they
# cannot be selected). failure_code/message and event_data ride the list, no separate detail.
_LIST_COLUMNS = (
    "id",
    "event_timestamp",
    "trace_id",
    "tenant_id",  # projected for fleet attribution (Chunk 1); nullable — system rows carry NULL (RLS OR-NULL)
    "prior_trace_id",
    "service_name",
    "stage",
    "event_scope",
    "outcome",
    "row_count",
    "rows_succeeded",
    "rows_failed",
    "duration_ms",
    "mapping_version_id",
    "failure_code",
    "failure_message",
    "event_data",
)


def _tenant_term(scope: ReadScope) -> list[ColumnElement[bool]]:
    """The in-query tenant predicate (Slice 17b): applied for a pinned (TENANT) scope,
    OMITTED for PLATFORM see-all (the RLS USING branch is the see-all isolation).

    Conditioned on ``scope.is_platform``, NEVER on ``tenant_id`` being absent - so a TENANT
    scope ALWAYS carries the predicate (the catastrophe invariant). For audit specifically
    the predicate also excludes ``tenant_id IS NULL`` system rows from a TENANT read (the
    USING branch would otherwise admit them to every tenant); for PLATFORM the policy widens
    reads and the predicate must not re-pin.
    """
    if scope.is_platform:
        return []
    if scope.tenant_id is None:  # unreachable: a pinned scope always carries a UUID
        raise TenantScopeError("a pinned read scope carries no tenant", tenant_id=None)
    return [AuditEvent.tenant_id == scope.tenant_id]


def _filters(
    scope: ReadScope,
    *,
    trace_id: UUID | None,
    outcomes: list[str] | None,
    window_cutoff: datetime | None,
) -> list[ColumnElement[bool]]:
    """The WHERE terms (tenant predicate first, when pinned). Filters are DB vocabulary
    already (the handler translated wire -> DB)."""
    terms: list[ColumnElement[bool]] = _tenant_term(scope)
    if trace_id is not None:
        terms.append(AuditEvent.trace_id == trace_id)
    if outcomes is not None:
        # An empty list means "this wire bucket maps to no DB value" -> IN () matches nothing,
        # the honest result, never "no filter".
        terms.append(AuditEvent.outcome.in_(outcomes))
    if window_cutoff is not None:
        terms.append(AuditEvent.event_timestamp >= window_cutoff)
    return terms


async def list_events(
    engine: AsyncEngine,
    scope: ReadScope,
    *,
    limit: int,
    trace_id: UUID | None = None,
    outcomes: list[str] | None = None,
    window_cutoff: datetime | None = None,
) -> Sequence[Row[Any]]:
    """The tenant's recent audit events (newest first), filtered, bounded to ``limit``.

    TENANT sees its own (system ``tenant_id IS NULL`` rows excluded by the predicate);
    PLATFORM see-all reads across every tenant, including system rows, via the policy USING
    branch. ``event_timestamp DESC`` with ``id`` (UUIDv7, time-ordered) as the stable
    tie-breaker; ``limit`` bounds the high-volume table (no pagination this slice).
    """
    columns = [getattr(AuditEvent, name) for name in _LIST_COLUMNS]
    statement = (
        # LEFT JOIN identity_mirror.tenants for tenant_name (Chunk 9). audit.events.tenant_id is
        # NULLABLE (system rows) — the LEFT JOIN yields NULL tenant_name for those (correct), and
        # never drops a row. Keyed on the tenant PK (≤1 match); RLS-OFF table (D41).
        select(*columns, TenantRow.name.label("tenant_name"))
        .select_from(AuditEvent)
        .outerjoin(TenantRow, TenantRow.tenant_id == AuditEvent.tenant_id)
        .where(*_filters(scope, trace_id=trace_id, outcomes=outcomes, window_cutoff=window_cutoff))
        .order_by(AuditEvent.event_timestamp.desc(), AuditEvent.id.desc())
        .limit(limit)
    )
    async with read_session(engine, is_platform=scope.is_platform, tenant_id=scope.tenant_id) as conn:
        return list((await conn.execute(statement)).all())


__all__ = ["list_events"]
