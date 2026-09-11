"""Per-stage fire-and-forget audit emission.

One thin wrapper over the ``dis-audit`` writer. Stage vocabulary is dis-audit's
CLOSED enum — this consumer adds no members. The mapping for this service:

- intake + bronze/GCS fetch → ``Stage.RECEIVED`` (no consumer-fetch member exists;
  ``service_name`` disambiguates from the receivers)
- mapping load + routing → ``Stage.MAPPING_LOOKED_UP``
- the two gates → ``Stage.PRE_MAPPING_VALIDATED`` / ``Stage.POST_MAPPING_VALIDATED``
- the engine → ``Stage.MAPPING_EXECUTED``
- the dual-write → ``Stage.CANONICAL_WRITTEN``
- ``Stage.IDENTITY_VALIDATED`` is deliberately NEVER emitted: no Identity Service
  call exists; the composite FK is the enforcement.

**Duplicate representation**: a dedup-key hit emits a ROW-scoped
``CANONICAL_WRITTEN`` event whose ``outcome`` IS the kind —
``DUPLICATE_NOOP`` (byte-identical redelivery; insert suppressed) |
``DUPLICATE_OVERWRITTEN`` (correction; insert landed) — with ``prior_trace_id``
as a first-class column so the duplicate is console-queryable; the non-queried
detail stays in ``event_data``::

    {"row_hash": …,
     "dedup_key": {"store_id": …, "source_id": …, "source_event_id": …}}

Every event carries the known ``tenant_id``, the read ``trace_id``,
``mapping_version_id`` where known, and the bronze id as the load-bearing id.
Failures in emission are logged and NEVER raised (the one sanctioned swallow);
duplicate audit rows are tolerated.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from dis_audit import AuditEvent, AuditWriter, EventScope, Outcome, Stage
from dis_core.logging import get_logger
from dis_core.timestamps import now_utc
from streaming_consumer.config import SERVICE_NAME
from streaming_consumer.sinks.canonical import DuplicateHit

_log = get_logger(SERVICE_NAME)


class ConsumerAudit:
    """Builds and emits this consumer's stage events, fire-and-forget."""

    def __init__(self, writer: AuditWriter) -> None:
        self._writer = writer

    async def emit(
        self,
        *,
        stage: Stage,
        outcome: Outcome,
        tenant_id: UUID,
        trace_id: UUID,
        scope: EventScope = EventScope.INGRESS_EVENT,
        bronze_id: UUID | None = None,
        prior_trace_id: UUID | None = None,
        mapping_version_id: int | None = None,
        row_count: int | None = None,
        rows_succeeded: int | None = None,
        rows_failed: int | None = None,
        row_offset: int | None = None,
        duration_ms: int | None = None,
        event_data: dict[str, Any] | None = None,
        failure_code: str | None = None,
        failure_message: str | None = None,
    ) -> None:
        """Emit one stage event. Never raises; never blocks the data path.

        ``failure_code`` takes a :class:`~dis_audit.FailureCode` member (a
        ``StrEnum``, so the parameter stays ``str``-typed) — the stable
        failure vocabulary; ``duration_ms`` is the orchestrator's lap-timer
        stage span.
        """
        log = _log.bind(stage=str(stage.value), tenant_id=str(tenant_id), trace_id=str(trace_id))
        try:
            event = AuditEvent(
                event_timestamp=now_utc(),
                trace_id=trace_id,
                prior_trace_id=prior_trace_id,
                tenant_id=tenant_id,
                data_ingress_event_id=bronze_id,
                service_name=SERVICE_NAME,
                stage=stage,
                event_scope=scope,
                outcome=outcome,
                mapping_version_id=mapping_version_id,
                row_count=row_count,
                rows_succeeded=rows_succeeded,
                rows_failed=rows_failed,
                row_offset=row_offset,
                duration_ms=duration_ms,
                event_data=event_data,
                failure_code=failure_code,
                failure_message=failure_message,
            )
            written = await self._writer.write(event)
            if not written:
                # The writer already logged its own failure detail; this line is the
                # service-side alert-worthy marker so silent audit loss stays visible.
                log.error("audit write reported failure; data path continues")
        except Exception:  # noqa: BLE001 - the ONE sanctioned swallow: audit never blocks the data path
            log.exception("audit emission raised; swallowed so the data path continues")

    async def emit_duplicate(
        self,
        hit: DuplicateHit,
        *,
        tenant_id: UUID,
        store_id: UUID,
        source_id: str,
        trace_id: UUID,
        bronze_id: UUID,
        mapping_version_id: int,
    ) -> None:
        """One ROW-scoped duplicate event — the column representation.

        ``hit.kind`` is exactly the ``DUPLICATE_NOOP`` | ``DUPLICATE_OVERWRITTEN``
        vocabulary, so the outcome IS the kind. Only the queried-by fields are columns;
        ``row_hash`` and ``dedup_key`` stay in ``event_data``.

        The two kinds mean different things about the write:

        - ``DUPLICATE_OVERWRITTEN`` — a correction. The insert LANDED (``rows_succeeded=1``).
        - ``DUPLICATE_NOOP`` — a byte-identical redelivery. The insert was SUPPRESSED
          (``rows_succeeded=0``), plus an explicit ``suppressed``/``suppression_reason``
          pair in ``event_data``.

        The stage stays ``CANONICAL_WRITTEN`` deliberately, and the row count is what
        carries the truth. A stage name is a PIPELINE LOCATION — where the event
        occurred — not an assertion that a row was written; every other member of the
        closed vocabulary reads the same way, and FAILURE outcomes are emitted under
        it too. Minting a stage would mean migrating
        ``ck_audit_events_stage_vocab``, the BigQuery ``stage`` description and every
        importer, to say something ``rows_succeeded=0`` already says exactly.

        Emitting this event at all is the point: with the insert suppressed, this row is
        the ONLY evidence that a retry occurred. ``prior_trace_id`` ties it to the
        delivery that actually landed the data.
        """
        suppressed = hit.kind == "DUPLICATE_NOOP"
        event_data: dict[str, object] = {
            "row_hash": hit.row_hash,
            "dedup_key": {
                "store_id": str(store_id),
                "source_id": source_id,
                "source_event_id": hit.source_event_id,
            },
            "suppressed": suppressed,
        }
        if suppressed:
            event_data["suppression_reason"] = (
                "redelivery: identical payload hash under an existing dedup key; insert "
                "suppressed by the 0019 redelivery filter (uq_*_redelivery backstop). "
                "A correction would differ in row_hash and would have been appended."
            )
        await self.emit(
            stage=Stage.CANONICAL_WRITTEN,
            outcome=Outcome(hit.kind),
            scope=EventScope.ROW,
            tenant_id=tenant_id,
            trace_id=trace_id,
            prior_trace_id=hit.prior_trace_id,
            bronze_id=bronze_id,
            mapping_version_id=mapping_version_id,
            row_offset=hit.chunk_row_index,
            rows_succeeded=0 if suppressed else 1,
            event_data=event_data,
        )
