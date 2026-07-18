"""Wire shapes + the single outcome crosswalk for the audit event log (GET /audit).

One endpoint consumes this: ``GET /audit`` - the tenant's recent pipeline audit events,
newest first, filterable by trace, outcome, and time window.

The load-bearing rule (the quarantine "one canonical truth" principle): there is ONE
``outcome`` (DB CHECK vocab) -> ``OutcomeWire`` crosswalk here, and it drives BOTH the
displayed Outcome AND the ``outcome`` filter. Display reads it forward (DB -> wire); the
filter reads it in reverse (wire -> the set of DB values for the WHERE). Because both sides
read the same dict, the filter cannot drift from the display. The ``DUPLICATE_*`` pair -
which the DDL notes REFINES SUCCESS but keeps queryable - collapses to one ``duplicate``
wire bucket (the reverse crosswalk returns both DB members), exactly as the quarantine stage
crosswalk collapses leftovers into ``other``. Lookup is EXPLICIT (never ``.get`` with a
default): a genuinely NEW DB outcome is absent from the map and fails loud (KeyError -> 500),
the no-silent-fallback posture (root CLAUDE.md code-quality rule 4).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# Wire vocabularies (DB vocab never leaks; the UI sees these only).
EventScopeWire = Literal["INGRESS_EVENT", "ROW"]
WindowWire = Literal["24h", "7d", "30d"]
OutcomeWire = Literal["success", "failure", "skipped", "retried", "duplicate"]

# THE crosswalk (DB outcome -> wire bucket). The CHECK ck_audit_events_outcome_vocab members
# map here 1:1 except the DUPLICATE_* pair, which the DDL says REFINES SUCCESS; it collapses
# to one queryable ``duplicate`` bucket so the distinction survives without a sixth button.
# Explicit, not ``.get`` - a new DB member fails loud (KeyError -> 500).
_OUTCOME_DB_TO_WIRE: dict[str, OutcomeWire] = {
    "SUCCESS": "success",
    "FAILURE": "failure",
    "SKIPPED": "skipped",
    "RETRIED": "retried",
    "DUPLICATE_NOOP": "duplicate",
    "DUPLICATE_OVERWRITTEN": "duplicate",
}


def outcome_to_wire(outcome: str) -> OutcomeWire:
    """Forward crosswalk for the displayed Outcome. KeyError (500) on an unknown member."""
    return _OUTCOME_DB_TO_WIRE[outcome]


def outcome_db_values_for(outcome: OutcomeWire) -> list[str]:
    """Reverse crosswalk for the ``outcome`` filter: the DB values in this wire bucket."""
    return [db for db, wire in _OUTCOME_DB_TO_WIRE.items() if wire == outcome]


class AuditEventRow(BaseModel):
    """One audit event in the log (fields per the served columns of ``audit.events``).

    ``auth_principal`` and ``client_ip`` are deliberately ABSENT: caller-context PII that
    never reaches the tenant wire. The UI renders the "Who" column from ``service_name`` +
    the token's ``user_type`` (non-PII); a NAMED-actor display is pending a decision on
    ``auth_principal`` exposure (docs/decisions.md), not built this slice.
    """

    id: str
    trace_id: str
    # The owning tenant. OPTIONAL by design: a PLATFORM see-all read surfaces system rows whose
    # tenant_id IS NULL (the RLS USING OR-NULL branch) — those carry null here (Chunk 1).
    tenant_id: str | None
    # identity_mirror.tenants.name; null for system rows (tenant_id NULL) or an unmirrored tenant (Chunk 9).
    tenant_name: str | None
    prior_trace_id: str | None  # the redelivery's prior trace; null on non-duplicate rows
    event_timestamp: str  # ISO-8601, UTC offset rendered as Z
    service_name: str  # the emitting service (the non-PII actor)
    stage: str  # the pipeline stage (raw DB member; open vocabulary, wired as-is)
    event_scope: EventScopeWire  # INGRESS_EVENT (chunk summary) or ROW (per-row record)
    outcome: OutcomeWire  # the single crosswalk
    row_count: int | None
    rows_succeeded: int | None
    rows_failed: int | None
    duration_ms: int | None
    mapping_version: int | None  # from mapping_version_id; null for pre-lookup stages
    failure_code: str | None
    failure_message: str | None
    event_data: dict[str, object] | None  # stage-specific structured context, passthrough


class AuditEventListResponse(BaseModel):
    """The list body: the tenant's recent audit events (bounded newest-first, no paging)."""

    items: list[AuditEventRow]
