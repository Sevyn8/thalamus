"""The consumer's quarantine sink — builds held records off the envelope + flow context.

The thin wrapper over ``dis-quarantine`` (the ``ConsumerAudit`` pattern): this module
owns the mapping from a failure (the envelope, the ``_FlowContext`` ids, the audit
``Stage`` it died in, the stable ``FailureCode``) to the columns of the two live
``quarantine.*`` tables. The ALLOWLIST decision is NOT here — ``orchestrate.py``
decides WHAT is quarantinable; this sink only knows HOW to hold it.

**Fail-loud (the deliberate asymmetry with ``sinks/audit.py``):** quarantine is the
held thing itself, the data path — every method RAISES on failure so the caller
falls back to nack (never ack-and-lose). The QUARANTINED *audit* emit stays
fire-and-forget and happens at the call site AFTER the hold succeeds.

Correlation (the D78 seam): ``data_ingress_event_id`` is the bronze row id (the
envelope's ``bronze_ref``, cross-checked by fetch); records carry ``trace_id`` +
``tenant_id`` always, ``mapping_version_id`` where known (post-lookup; NOT NULL on
the rows table — row-grain failures only exist post-lookup). ``failure_context``
carries the per-failure detail the gate computed — column/check/reason plus, where
the failure carried them, the offending ``value`` and the mapping cell fields
(``source_column``/``expected_format``/``transform_index``) (Slice 52b, the
``failures[]`` grain). The raw ROW/payload still never lands here — it stays in GCS,
located by ``gcs_uri`` + ``row_offset``. The SAME failures list feeds the audit
projection, which stays value-free by construction (it never reads ``value``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from dis_audit import FailureCode, Stage
from dis_core.errors import QuarantineWriteError
from dis_core.timestamps import now_utc
from dis_quarantine import (
    PostgresQuarantineWriter,
    QuarantinedChunk,
    QuarantinedRow,
    failure_stage_for,
)
from streaming_consumer.envelope import IngressReadyEvent

if TYPE_CHECKING:
    from streaming_consumer.orchestrate import _FlowContext


@dataclass(frozen=True, slots=True)
class GateFailure:
    """One gate failure as the orchestrator carries it to the sink (Slice 52b).

    ``check`` + ``reason`` are always present; every other field is conditional on the
    failure type (Pandera source/canonical shape vs mapping cell-normalization) and is
    persisted into ``failure_context.failures[]`` ONLY when present — never fabricated.
    The audit projection reads ONLY check/column/row_index/reason and NEVER ``value``
    (the shared-failures seam: quarantine keeps the value, audit stays value-free).
    """

    check: str
    reason: str
    column: str | None = None
    row_index: int | None = None
    value: str | None = None
    source_column: str | None = None
    expected_format: str | None = None
    transform_index: int | None = None


def _failure_element(f: GateFailure, *, include_row_index: bool) -> dict[str, object]:
    """One ``failure_context.failures[]`` element (Slice 52b) — the element shape, once.

    ``check`` + ``reason`` are always written; every other field is appended ONLY when
    the failure object actually carried it (AC1: absent fields are OMITTED, never
    null-filled, never fabricated). ``value`` (the offending cell) is capped WIDER than
    the descriptions — it is data future correction needs whole, not a description.
    ``row_index`` is written for the chunk builder (row-less shape, no ``row_offset``
    column) and omitted for the row builder (where it is hoisted to ``row_offset``).
    """
    element: dict[str, object] = {"check": f.check[:256], "reason": f.reason[:512]}
    if f.column is not None:
        element["column"] = f.column
    if include_row_index and f.row_index is not None:
        element["row_index"] = f.row_index
    if f.value is not None:
        element["value"] = f.value[:2048]  # data, not description — wider cap (52b)
    if f.source_column is not None:
        element["source_column"] = f.source_column
    if f.expected_format is not None:
        element["expected_format"] = f.expected_format
    if f.transform_index is not None:
        element["transform_index"] = f.transform_index
    return element


class ConsumerQuarantine:
    """Builds and holds this consumer's quarantined failures. Fail-loud."""

    def __init__(self, writer: PostgresQuarantineWriter) -> None:
        self._writer = writer

    async def hold_chunk_failure(
        self,
        event: IngressReadyEvent,
        ctx: _FlowContext,
        *,
        stage: Stage,
        failure_code: FailureCode,
        message: str,
        exception_class: str | None = None,
        failures: list[GateFailure] | None = None,
    ) -> None:
        """Hold the whole chunk in ``quarantined_chunks`` (status=NEW), or raise.

        ``dis_channel`` comes from the bronze row (post-fetch); a pre-fetch call is
        a caller bug — the allowlist guard excludes it — and raises so the message
        nacks rather than acks-and-loses.
        """
        if ctx.dis_channel is None:
            raise QuarantineWriteError(
                "hold_chunk_failure called pre-fetch (dis_channel unknown) — the allowlist "
                "guard must exclude pre-fetch failures (caller bug)",
                tenant_id=str(event.tenant_id),
                trace_id=str(event.trace_id),
                failure_code=str(failure_code),
            )
        context: dict[str, object] = {"failure_message": message[:2000]}
        if exception_class is not None:
            context["exception_class"] = exception_class
        if failures is not None:
            # Per-failure detail (Slice 52b): the row-less shape routed here keeps
            # row_index in the element (no row_offset column on the chunk table);
            # value + mapping detail are appended only where the failure carried them.
            context["failures"] = [_failure_element(f, include_row_index=True) for f in failures]
        record = QuarantinedChunk(
            tenant_id=event.tenant_id,
            store_id=event.store_id,
            data_ingress_event_id=ctx.bronze_id or event.bronze_ref,
            trace_id=event.trace_id,
            source_id=event.source_id,
            dis_channel=ctx.dis_channel,
            gcs_uri=event.gcs_uri,
            failure_stage=failure_stage_for(stage),
            failure_reason=str(failure_code),
            failure_context=context,
            mapping_version_id=ctx.mapping_version_id,
            row_count_in_chunk=ctx.row_count,
            quarantined_at=now_utc(),
        )
        await self._writer.hold_chunk(record)

    async def hold_row_failures(
        self,
        event: IngressReadyEvent,
        ctx: _FlowContext,
        *,
        stage: Stage,
        failures: list[GateFailure],
    ) -> int:
        """Hold the gate's failing rows in ``quarantined_rows`` (status=NEW), or raise.

        One record per DISTINCT failing row (a row with several failed checks is
        one held row); ``failure_context.failures`` aggregates that row's per-failure
        detail (column/check/reason plus value + mapping fields where the failure
        carried them, Slice 52b). Returns the number of rows held. Every failure
        must carry a ``row_index`` (the row-less shape routes to the chunk table at
        the call site) and the mapping must be loaded (``mapping_version_id`` is
        NOT NULL on the live rows table).
        """
        if ctx.dis_channel is None or ctx.mapping_version_id is None:
            raise QuarantineWriteError(
                "hold_row_failures called before fetch/lookup completed (caller bug): "
                f"dis_channel={ctx.dis_channel!r}, mapping_version_id={ctx.mapping_version_id!r}",
                tenant_id=str(event.tenant_id),
                trace_id=str(event.trace_id),
                failure_code=str(FailureCode.VALIDATION_ROW_FAILED),
            )
        by_row: dict[int, list[GateFailure]] = {}
        for failure in failures:
            row_index = failure.row_index
            if row_index is None:
                raise QuarantineWriteError(
                    "hold_row_failures received a row-less failure — the call site routes "
                    "those to quarantined_chunks (caller bug)",
                    tenant_id=str(event.tenant_id),
                    trace_id=str(event.trace_id),
                    failure_code=str(FailureCode.VALIDATION_ROW_FAILED),
                )
            by_row.setdefault(row_index, []).append(failure)
        records = [
            QuarantinedRow(
                tenant_id=event.tenant_id,
                store_id=event.store_id,
                data_ingress_event_id=ctx.bronze_id or event.bronze_ref,
                trace_id=event.trace_id,
                source_id=event.source_id,
                dis_channel=ctx.dis_channel,
                gcs_uri=event.gcs_uri,
                row_offset=row_index,
                failure_stage=failure_stage_for(stage),
                failure_reason=str(FailureCode.VALIDATION_ROW_FAILED),
                failure_context={
                    "failures": [_failure_element(f, include_row_index=False) for f in row_failures]
                },
                mapping_version_id=ctx.mapping_version_id,
                quarantined_at=now_utc(),
            )
            for row_index, row_failures in sorted(by_row.items())
        ]
        await self._writer.hold_rows(records)
        return len(records)
