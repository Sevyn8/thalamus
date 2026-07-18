"""Wire shapes + the single verdict crosswalk for the Ingestion Runs log (GET /runs).

One endpoint consumes this: ``GET /runs`` — the tenant's recent ingress runs (one row per
ingress execution in ``bronze.data_ingress_events``), newest first, filterable by status and
time window.

**Run state is derived from the AUDIT TRAIL, not from bronze (Slice 51a, D117).** Bronze's
``processing_status`` is an ingress-only signal that the pipeline never advances past
RECEIVED/PUBLISHED (the schema's declared "consumer advances it" design is SUPERSEDED, D117);
the completion truth lives in ``audit.events``. The displayed ``status`` is the VERDICT derived
from the run's terminal audit event.

THE crosswalk (the "one canonical truth" principle, D118): there is ONE terminal-marking
``(stage, outcome) -> verdict`` map here — :data:`TERMINAL_CROSSWALK` — and it is the SINGLE
source for BOTH the Python display lookup (:func:`verdict_of`) AND the SQL terminal-marking
predicate / precedence-rank / filter that ``repos/runs.py`` builds by iterating it. Because both
sides read the same tuple, they cannot drift. Lookup is EXPLICIT and FAIL-LOUD: an unmapped
terminal-marking pair raises (no ``.get`` default, no guessed verdict — the no-silent-fallback
posture, mirroring the prior status crosswalk). The quarantine case keys on the PAIR, never on
``outcome`` alone, because a QUARANTINED disposition is recorded with ``outcome=SUCCESS`` (the
FAILURE row already recorded the failure); reading outcome alone would call it "succeeded".

Counts (D119): three INDEPENDENT recorded numbers — ``input_row_count`` (bronze total),
``accepted`` (path-aware, from the terminal CANONICAL_WRITTEN event), ``quarantined`` (one
bucket, from the QUARANTINED event). The response NEVER asserts ``accepted + quarantined ==
input_row_count``: input is the worker's DuckDB-preflight count while accepted/quarantined derive
from the consumer's Polars parse — two parsers, equal in the normal case but not guaranteed. All
three are exposed so any discrepancy is representable, never hidden. There is deliberately NO
accepted/needs-review/rejected three-way split — the distinction is not recorded (D119, criterion 6).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# Wire vocabularies (DB vocab never leaks; the UI sees these only).
MethodWire = Literal["csv_upload", "api", "csv_erp", "reverse_api"]  # dis_channel, passthrough
WindowWire = Literal["24h", "7d", "30d"]
# The four honest run verdicts. ``processing`` = no terminal audit event yet (in flight or
# stalled — this slice does not distinguish the two, D118). The three terminal verdicts derive
# from the audit terminal-marking crosswalk below.
StatusWire = Literal["processing", "succeeded", "quarantined", "failed"]

# The canonical current-position (catalogue/snapshot) target — the write path whose
# CANONICAL_WRITTEN audit event carries ``event_rows_written = 0`` and the real accepted count in
# ``event_data`` (hot_rows_upserted + hot_noops). Matched against ``event_data.written_to_table``
# to pick the path-aware accepted figure (D119).
CATALOGUE_TABLE = "canonical.store_sku_current_position"

# THE terminal-marking crosswalk, in PRECEDENCE order (highest first). Each rule is
# ``(stage | None, outcome) -> verdict``; ``stage=None`` means "any stage" (the FAILURE case).
# THE SINGLE SOURCE for both :func:`verdict_of` and the SQL predicate/rank/filter in
# ``repos/runs.py`` — they are generated from this tuple, so they cannot drift (D118).
# Precedence (tuple order) resolves a run that carries more than one terminal-marking event
# (e.g. a gate FAILURE followed by a QUARANTINED disposition -> quarantined; a FAILURE then a
# later CANONICAL_WRITTEN on redelivery -> succeeded). Order-independent of event timestamps.
TERMINAL_CROSSWALK: tuple[tuple[str | None, str, StatusWire], ...] = (
    ("CANONICAL_WRITTEN", "SUCCESS", "succeeded"),
    ("QUARANTINED", "SUCCESS", "quarantined"),
    (None, "FAILURE", "failed"),
)

# The verdict when a run has NO terminal-marking audit event (still in flight, or stalled).
PROCESSING: StatusWire = "processing"


def _rule_matches(rule_stage: str | None, rule_outcome: str, stage: str, outcome: str) -> bool:
    return outcome == rule_outcome and (rule_stage is None or rule_stage == stage)


def verdict_of(stage: str, outcome: str) -> StatusWire:
    """Map a terminal-marking ``(stage, outcome)`` to its verdict (display side).

    FAIL-LOUD: an unmapped pair raises :class:`KeyError` (-> 500) — never a guessed default
    (the no-silent-fallback posture, D118). The repo only ever hands this a pair that the SQL
    terminal-marking predicate (built from the SAME :data:`TERMINAL_CROSSWALK`) selected, so a
    raise here means the crosswalk and the predicate drifted — which the structural test forbids.
    """
    for rule_stage, rule_outcome, verdict in TERMINAL_CROSSWALK:
        if _rule_matches(rule_stage, rule_outcome, stage, outcome):
            return verdict
    raise KeyError(f"unmapped terminal-marking audit pair (stage={stage!r}, outcome={outcome!r})")


class RunRow(BaseModel):
    """One ingress run: the bronze identity + the audit-derived run state + display names.

    Every entity travels as an id + a display name; the name is null where it cannot resolve
    (store absent on the run, no source-registry row, older runs predate templates — D119,
    criterion 3), never an error. ``auth_principal`` / ``client_ip`` / ``user_agent`` / ``gcs_uri``
    are deliberately ABSENT (caller-context PII + payload location; never on the tenant wire).
    """

    id: str
    trace_id: str
    tenant_id: str  # the owning tenant (bronze.tenant_id, NOT NULL) — fleet attribution (Chunk 1)
    tenant_name: str | None  # identity_mirror.tenants.name; null when tenant unmirrored (Chunk 9)
    store_id: str | None  # null when store identity is deferred to the consumer
    store_name: str | None  # identity_mirror.stores.name; null when store_id is null / unmirrored
    source_id: str  # the pipeline id
    source_name: str | None  # config.sources.display_name; null when the source has no registry row
    template_id: str | None  # bronze replay-lineage template; null on pre-Slice-8 runs
    template_name: str | None  # config.source_mappings.template_name; null when unresolved
    method: MethodWire  # dis_channel, passthrough
    # The audit-derived verdict (D117/D118). Wire key stays ``status`` for contract stability;
    # its VALUE is now the verdict, not bronze.processing_status.
    status: StatusWire
    mapping_version: int | None  # from the terminal audit event's mapping_version_id
    seen_before: bool  # a recorded duplicate outcome exists for this run (D119, criterion 5)
    source_payload_id: str | None  # the File / event ref (upload_session_id)
    file_name: str | None  # the uploaded file's original name; null on pre-Slice-51a runs (D120)
    # The three INDEPENDENT counts (D119). The response never asserts accepted + quarantined ==
    # input_row_count (two parsers); all three are exposed so any discrepancy is representable.
    input_row_count: int | None  # bronze.row_count (the payload total; worker DuckDB preflight)
    accepted: int | None  # rows committed to canonical (path-aware); null unless terminal
    quarantined: int | None  # ONE bucket of held/rejected rows; null unless quarantined-verdict
    received_at: str  # When — ISO-8601, UTC as Z
    published_at: str | None  # receiver -> consumer handoff
    completed_at: str | None  # the terminal audit event's timestamp; null while processing


class RunListResponse(BaseModel):
    """The list body: one keyset page of the tenant's recent ingress runs (newest first).

    ``next_cursor`` is the opaque token for the next (older) page, or ``null`` when no more
    runs remain (Slice 51b, D124). The envelope augments the bare ``{items: [...]}`` house
    shape with this one field (the quarantine ``open_count`` precedent)."""

    items: list[RunRow]
    next_cursor: str | None = None
