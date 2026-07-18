"""Per-stage fire-and-forget audit emission for a connector (WorkerAudit pattern).

A near-copy of csv-ingest-worker's ``WorkerAudit`` with the ``service_name`` made a
constructor argument, so a connector's audit rows are attributed to the connector
(e.g. ``thalamus-square``) rather than to the CSV worker. Stage/scope/outcome and the
FailureCode vocabulary are dis-audit's closed enums (the connector adds none).

Fire-and-forget (hard rule 11): a write failure is logged and never raised, never
blocking the data path (the one sanctioned swallow, code-quality rule 6).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from dis_audit import AuditEvent, AuditWriter, EventScope, Outcome, Stage
from dis_core.logging import get_logger
from dis_core.timestamps import now_utc


class ConnectorAudit:
    """Builds and emits a connector's stage events, fire-and-forget."""

    def __init__(self, writer: AuditWriter, *, service_name: str) -> None:
        self._writer = writer
        self._service_name = service_name
        self._log = get_logger(service_name)

    async def emit(
        self,
        *,
        stage: Stage,
        outcome: Outcome,
        tenant_id: UUID,
        trace_id: UUID,
        bronze_id: UUID | None = None,
        prior_trace_id: UUID | None = None,
        row_count: int | None = None,
        duration_ms: int | None = None,
        event_data: dict[str, Any] | None = None,
        failure_code: str | None = None,
        failure_message: str | None = None,
    ) -> None:
        """Emit one stage event. Never raises; never blocks the data path."""
        log = self._log.bind(stage=str(stage.value), tenant_id=str(tenant_id), trace_id=str(trace_id))
        try:
            event = AuditEvent(
                event_timestamp=now_utc(),
                trace_id=trace_id,
                prior_trace_id=prior_trace_id,
                tenant_id=tenant_id,
                data_ingress_event_id=bronze_id,
                service_name=self._service_name,
                stage=stage,
                event_scope=EventScope.INGRESS_EVENT,
                outcome=outcome,
                row_count=row_count,
                duration_ms=duration_ms,
                event_data=event_data,
                failure_code=failure_code,
                failure_message=failure_message,
            )
            written = await self._writer.write(event)
            if not written:
                log.error("audit write reported failure; data path continues (hard rule 11)")
        except Exception:  # noqa: BLE001 - the ONE sanctioned swallow (hard rule 11)
            log.exception("audit emission raised; swallowed so the data path continues")
