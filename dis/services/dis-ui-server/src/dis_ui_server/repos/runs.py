"""``bronze.data_ingress_events`` + audit-derived run state — the Ingestion Runs data access.

READ-ONLY (D111): dis-ui-server reads bronze for the runs surface; the streaming consumer +
receivers remain bronze's SOLE writers. This module builds SELECT-only statements (core-style on
the ``read_session`` connection, service CLAUDE.md durable invariant) — never an
INSERT/UPDATE/DELETE, never ``text()`` raw SQL, never an ``AsyncSession``.

Run state derives from ``audit.events`` (Slice 51a, D117): a correlated LATERAL picks the run's
top-precedence terminal-marking audit event (verdict/counts/completion), plus a ``seen_before``
EXISTS over the recorded duplicate outcomes, plus LEFT JOINs for the store / source / template
display names. The terminal-marking predicate, the precedence rank, and the verdict-filter CASE
are all GENERATED from :data:`schemas.runs.TERMINAL_CROSSWALK` (the single source shared with the
Python :func:`~schemas.runs.verdict_of`), so the SQL and the Python mapping cannot drift (D118).

TENANT SCOPING (the hard-limit posture): every tenant_id table carries an explicit predicate,
each equating its ``tenant_id`` to the bronze row's; bronze is pinned by ``_tenant_term``
(PLATFORM see-all omits it, the RLS USING branch is the isolation). The LOAD-BEARING predicate is
``config.sources``: ``source_id`` is tenant-shared, so without the predicate a run's join fans out
to every tenant's row of that source (a cross-tenant ``display_name`` leak — proven: 1 row with the
predicate, 2 without). On ``identity_mirror.stores`` (RLS-OFF, D41) the predicate is
defense-in-depth, NOT the sole isolation: ``store_id`` is globally unique (``uq_ims_store_id``) and
reached through the composite ``bronze→stores`` FK, so it cannot resolve cross-tenant; likewise the
audit LATERAL and the template LATERAL key on unique ids (bronze ``id`` / ``template_id``). All
predicates are kept regardless (the hard-limit posture; D121). ``scope`` MUST come from the verified
token (``require_read_scope``); this module trusts its caller on that.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Row, and_, case, exists, literal, or_, select, true, tuple_
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import aliased

from dis_core.errors import TenantScopeError
from dis_ui_server.auth.scope import ReadScope
from dis_ui_server.db import read_session
from dis_ui_server.models import AuditEvent, DataIngressEvent, Source, SourceMappingRow, StoreRow, TenantRow
from dis_ui_server.pagination import Boundary
from dis_ui_server.schemas.runs import PROCESSING, TERMINAL_CROSSWALK, StatusWire

# Only whole-event (INGRESS_EVENT) audit rows carry run-level verdict/counts; ROW-scoped rows are
# per-row detail and must not drive the run verdict.
_INGRESS_SCOPE = "INGRESS_EVENT"
# The recorded duplicate outcomes (worker upload no-op + consumer row-level dedup) — the
# seen-before signal, read from audit, never recomputed (D119, criterion 5).
_DUPLICATE_OUTCOMES = ("DUPLICATE_NOOP", "DUPLICATE_OVERWRITTEN")


def _tenant_term(scope: ReadScope) -> list[ColumnElement[bool]]:
    """The bronze tenant predicate (Slice 17b): applied for a pinned (TENANT) scope, OMITTED for
    PLATFORM see-all (the RLS USING branch is the see-all isolation).

    Conditioned on ``scope.is_platform``, NEVER on ``tenant_id`` being absent — so a TENANT scope
    ALWAYS carries the predicate (the catastrophe invariant). bronze.tenant_id is NOT NULL.
    """
    if scope.is_platform:
        return []
    if scope.tenant_id is None:  # unreachable: a pinned scope always carries a UUID
        raise TenantScopeError("a pinned read scope carries no tenant", tenant_id=None)
    return [DataIngressEvent.tenant_id == scope.tenant_id]


def _keyset_term(after: Boundary) -> ColumnElement[bool]:
    """The keyset boundary as a ROW-VALUE comparison over ``(received_at DESC, id DESC)`` (D124).

    ``(received_at, id) < (:r, :i)`` — Postgres pushes this into the composite index
    ``(tenant_id, received_at DESC, id DESC)`` as a true seek (proven by live EXPLAIN: boundary
    as a full Index Cond, zero rows removed by filter). The OR-expanded equivalent
    (``received_at < :r OR (received_at = :r AND id < :i)``) is FORBIDDEN — it is never
    index-pushed and degrades to an offset-like scan from the newest row. ``id`` (UUIDv7 PK) is
    the total-order tie-break, so no row is skipped or repeated as new runs arrive above the
    boundary. The regression-guard unit test fails if this is ever rewritten to the OR form.
    """
    return tuple_(DataIngressEvent.received_at, DataIngressEvent.id) < (after.received_at, after.id)


# ---- SQL artifacts generated from TERMINAL_CROSSWALK (the single source, D118) ----


def _rule_condition(stage_col: Any, outcome_col: Any, rule_stage: str | None, rule_outcome: str) -> Any:
    """One terminal-marking rule as a SQL condition (``stage=None`` -> any stage)."""
    if rule_stage is None:
        return outcome_col == rule_outcome
    return and_(stage_col == rule_stage, outcome_col == rule_outcome)


def _terminal_predicate(stage_col: Any, outcome_col: Any) -> ColumnElement[bool]:
    """WHERE: the event is terminal-marking (its pair matches SOME crosswalk rule)."""
    return or_(*(_rule_condition(stage_col, outcome_col, rs, ro) for rs, ro, _v in TERMINAL_CROSSWALK))


def _precedence_rank(stage_col: Any, outcome_col: Any) -> Any:
    """ORDER BY key: the crosswalk index of the matched rule (lower = higher precedence)."""
    return case(
        *(
            (_rule_condition(stage_col, outcome_col, rs, ro), idx)
            for idx, (rs, ro, _v) in enumerate(TERMINAL_CROSSWALK)
        ),
        else_=len(TERMINAL_CROSSWALK),
    )


def _verdict_case(stage_col: Any, outcome_col: Any) -> Any:
    """SQL mirror of :func:`verdict_of`, generated from the SAME tuple — for the status FILTER
    only (display maps in Python via ``verdict_of``). Yields NULL for a non-terminal pair."""
    return case(
        *(
            (_rule_condition(stage_col, outcome_col, rs, ro), literal(verdict))
            for rs, ro, verdict in TERMINAL_CROSSWALK
        ),
        else_=None,
    )


def _terminal_lateral() -> Any:
    """The correlated LATERAL: the run's top-precedence terminal-marking audit event (or none)."""
    return (
        select(
            AuditEvent.stage.label("t_stage"),
            AuditEvent.outcome.label("t_outcome"),
            AuditEvent.event_timestamp.label("t_completed_at"),
            AuditEvent.rows_succeeded.label("t_rows_succeeded"),
            AuditEvent.row_count.label("t_row_count"),
            AuditEvent.event_data.label("t_event_data"),
            AuditEvent.mapping_version_id.label("t_mapping_version"),
        )
        .where(
            AuditEvent.data_ingress_event_id == DataIngressEvent.id,
            AuditEvent.event_scope == _INGRESS_SCOPE,
            AuditEvent.tenant_id == DataIngressEvent.tenant_id,  # explicit tenant predicate (join)
            _terminal_predicate(AuditEvent.stage, AuditEvent.outcome),
        )
        .order_by(
            _precedence_rank(AuditEvent.stage, AuditEvent.outcome).asc(),
            AuditEvent.event_timestamp.desc(),
            AuditEvent.id.desc(),
        )
        .limit(1)
        .lateral("run_terminal")
    )


def _template_lateral() -> Any:
    """The template display-name LATERAL (LIMIT 1: template_name is constant per template_id, but
    many version rows share it — avoid row fan-out). Explicit tenant predicate on the join."""
    return (
        select(SourceMappingRow.template_name.label("t_template_name"))
        .where(
            SourceMappingRow.tenant_id == DataIngressEvent.tenant_id,
            SourceMappingRow.template_id == DataIngressEvent.template_id,
        )
        .limit(1)
        .lateral("run_template")
    )


def _build_statement(
    scope: ReadScope,
    *,
    limit: int,
    status: StatusWire | None,
    window_cutoff: datetime | None,
    after: Boundary | None,
) -> Any:
    """Assemble the SELECT-only runs statement (extracted for compile-time testability).

    Over-fetches by one (``limit + 1``) so the caller can detect whether a further page
    exists without a COUNT (Slice 51b): ``> limit`` rows back => there is a next page.
    """
    terminal = _terminal_lateral()
    template = _template_lateral()
    dup = aliased(AuditEvent, name="dup")
    seen_before = exists(
        select(literal(1)).where(
            dup.data_ingress_event_id == DataIngressEvent.id,
            dup.tenant_id == DataIngressEvent.tenant_id,
            dup.outcome.in_(_DUPLICATE_OUTCOMES),
        )
    ).label("seen_before")

    terms: list[ColumnElement[bool]] = _tenant_term(scope)
    if status is not None:
        # Filter on the DERIVED verdict (D117): a non-terminal run -> "processing".
        verdict_expr = case(
            (terminal.c.t_stage.is_(None), literal(PROCESSING)),
            else_=_verdict_case(terminal.c.t_stage, terminal.c.t_outcome),
        )
        terms.append(verdict_expr == status)
    if window_cutoff is not None:
        terms.append(DataIngressEvent.received_at >= window_cutoff)
    if after is not None:
        # Keyset boundary: strictly-older rows over the (received_at DESC, id DESC) ordering,
        # as a ROW-VALUE comparison (index-pushable; the OR form is forbidden, D124).
        terms.append(_keyset_term(after))

    statement = (
        select(
            DataIngressEvent.id,
            DataIngressEvent.trace_id,
            DataIngressEvent.tenant_id,  # projected for fleet attribution (Chunk 1)
            TenantRow.name.label("tenant_name"),  # LEFT JOIN identity_mirror.tenants (Chunk 9)
            DataIngressEvent.store_id,
            DataIngressEvent.source_id,
            DataIngressEvent.dis_channel,
            DataIngressEvent.source_payload_id,
            DataIngressEvent.row_count,
            DataIngressEvent.template_id,
            DataIngressEvent.original_filename,
            DataIngressEvent.received_at,
            DataIngressEvent.published_at,
            StoreRow.name.label("store_name"),
            Source.display_name.label("source_name"),
            template.c.t_template_name.label("template_name"),
            terminal.c.t_stage,
            terminal.c.t_outcome,
            terminal.c.t_completed_at,
            terminal.c.t_rows_succeeded,
            terminal.c.t_row_count,
            terminal.c.t_event_data,
            terminal.c.t_mapping_version,
            seen_before,
        )
        .select_from(DataIngressEvent)
        .outerjoin(terminal, true())
        .outerjoin(template, true())
        # LEFT JOIN identity_mirror.tenants for tenant_name (Chunk 9). Keyed on the tenant PK, so
        # ≤1 match — no row fan-out; RLS-OFF table (D41), read under the existing read_session.
        .outerjoin(TenantRow, TenantRow.tenant_id == DataIngressEvent.tenant_id)
        .outerjoin(
            StoreRow,
            and_(
                StoreRow.tenant_id == DataIngressEvent.tenant_id,
                StoreRow.store_id == DataIngressEvent.store_id,
            ),
        )
        .outerjoin(
            Source,
            and_(
                Source.tenant_id == DataIngressEvent.tenant_id,
                Source.source_id == DataIngressEvent.source_id,
            ),
        )
        .where(*terms)
        .order_by(DataIngressEvent.received_at.desc(), DataIngressEvent.id.desc())
        .limit(limit + 1)  # over-fetch by one: > limit rows => a next page exists (Slice 51b)
    )
    return statement


async def list_runs(
    engine: AsyncEngine,
    scope: ReadScope,
    *,
    limit: int,
    status: StatusWire | None = None,
    window_cutoff: datetime | None = None,
    after: Boundary | None = None,
) -> Sequence[Row[Any]]:
    """The tenant's recent ingress runs (newest first), audit-derived, filtered, keyset-paged.

    TENANT sees its own (bronze RLS + the defense-in-depth predicate); PLATFORM see-all reads
    across every tenant via the policy USING branch. ``received_at DESC`` with ``id`` (UUIDv7) as
    the stable tie-breaker is the keyset cursor key (Slice 51b — do not destabilise). ``after``
    is the decoded cursor boundary (strictly-older rows). Returns up to ``limit + 1`` rows: the
    over-fetched extra signals a next page (the caller trims to ``limit`` and mints the cursor).
    """
    statement = _build_statement(scope, limit=limit, status=status, window_cutoff=window_cutoff, after=after)
    async with read_session(engine, is_platform=scope.is_platform, tenant_id=scope.tenant_id) as conn:
        return list((await conn.execute(statement)).all())


__all__ = ["list_runs"]
