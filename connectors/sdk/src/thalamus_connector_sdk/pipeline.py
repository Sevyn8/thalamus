"""The connector ingest pipeline: trigger in, CSV into bronze, ingress.ready out.

Mirrors csv-ingest-worker's ``pipeline.py`` with the PRODUCER inversion: the CSV worker
reads a pre-existing GCS object a producer wrote; the connector IS the producer, so the
worker's read-and-cross-check step is replaced by extract, serialize, upload. From the
bronze write onward the logic is the worker's, reused: dedup via ``find_prior``, the
metadata-only ``insert_row``, the ``ingress.ready`` publish after bronze lands, and
``mark_published`` (resume-and-mark on redelivery).

Identity and ``trace_id`` are READ off the trigger and never minted (the trigger is the
trust boundary); this module imports no ``dis_core.identity``. The only minted id is the
bronze row PK via ``dis_core`` ``new_uuid7``.

CONCURRENCY: the dedup is query-based, correct for a SINGLE worker instance; the
same caveat as the CSV worker's bronze dedup applies.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy.exc import (
    DisconnectionError,
    InterfaceError,
    InternalError,
    OperationalError,
)
from sqlalchemy.exc import TimeoutError as SATimeoutError
from sqlalchemy.ext.asyncio import AsyncEngine

from csv_ingest_worker.bronze import (
    CONTENT_TYPE,
    BronzeRow,
    PriorIngest,
    find_prior,
    insert_row,
    mark_published,
)
from csv_ingest_worker.config import INGRESS_READY_TOPIC
from csv_ingest_worker.pii_gate import gate_csv_headers
from csv_ingest_worker.publisher import IngressReadyEnvelope, Publisher
from dis_audit import Outcome, Stage
from dis_core.ids import new_uuid7
from dis_core.logging import get_logger
from dis_core.timestamps import ensure_utc, now_utc
from dis_pii import PiiBackend
from dis_rls import rls_session
from dis_storage import build_object_path
from thalamus_connector_sdk.adapter import (
    DROPPED_SAMPLE_MAX,
    RATE_LIMIT_EXHAUSTED,
    AuthContext,
    ConnectorAdapter,
    Cursor,
    ExtractResult,
    ExtractRow,
    PreflightResult,
    merge_rate_limit_state,
)
from thalamus_connector_sdk.audit import ConnectorAudit
from thalamus_connector_sdk.csv_serialize import DELIMITER, serialize_rows
from thalamus_connector_sdk.errors import ConnectorError
from thalamus_connector_sdk.health import (
    RATE_LIMIT_UNKNOWN,
    RateLimitState,
    upsert_health_error,
    upsert_health_seen,
)
from thalamus_connector_sdk.reason_codes import ConnectorReasonCode, failure_code_for_reason
from thalamus_connector_sdk.trigger import ConnectorTrigger

# The bronze provenance channel for API-pull connectors (already in the bronze CHECK
# vocab: csv_upload, api, csv_erp, reverse_api). Format stays CSV (CONTENT_TYPE).
API_CHANNEL = "api"

_SDK_SERVICE = "thalamus-connector-sdk"
_log = get_logger(_SDK_SERVICE)

# Tier 1 of the connector-health emit swallow: the DB errors that are genuinely
# TRANSIENT. A blip here must not kill ingest, so it is warned and swallowed
# (telemetry never blocks ingest). Deliberately NARROW: SQLAlchemy's ProgrammingError (bad
# SQL), ArgumentError and InvalidRequestError are programming defects and fall
# through to the tier-2 catch, which logs them at ERROR under a BUG marker.
# Nothing propagates from either tier, so a class missed here is loud, not fatal.
#
# All of these are raised through SQLAlchemy; psycopg is not imported (it is not a
# declared SDK dependency, and every DB call here goes through an AsyncConnection).
# OSError covers a raw socket refusal escaping the driver during connect.
_TRANSIENT_DB_ERRORS = (
    OperationalError,  # connection lost, server restart, too many connections, deadlock
    InterfaceError,  # connection broken out from under the driver
    InternalError,  # server-side internal / aborted transaction
    DisconnectionError,  # pool-level disconnect (not a DBAPIError)
    SATimeoutError,  # pool checkout timeout (not a DBAPIError)
    OSError,  # raw socket failure, e.g. ConnectionRefusedError
)

Disposition = Literal[
    "ingested",
    "duplicate_noop",
    "duplicate_resumed",
    "preflight_failed",
    "auth_failed",
    "extract_failed",
]


@dataclass
class _Lap:
    """Per-stage duration seam: stages run sequentially, so elapsed-since-the-prior-
    audit-point is the stage span at audit grain (the csv-ingest-worker pattern)."""

    _mark: float = field(default_factory=time.monotonic)

    def lap(self) -> int:
        now = time.monotonic()
        elapsed_ms = int((now - self._mark) * 1000)
        self._mark = now
        return max(elapsed_ms, 0)


class ObjectUploader(Protocol):
    """The write seam over dis-storage's client (tests inject a fake)."""

    def upload_bytes(self, object_path: str, data: bytes, *, content_type: str | None = None) -> None: ...


@dataclass(frozen=True)
class ConnectorOutcome:
    """What one trigger produced. ``trace_id`` is ALWAYS a read trace_id (the
    trigger's, or the prior ingest's on resume). ``next_cursor`` is the high-water
    mark for the next run (the primary domain's)."""

    disposition: Disposition
    trace_id: UUID
    bronze_id: UUID | None
    next_cursor: Cursor | None


@dataclass
class ConnectorPipeline:
    """One connector worker's wired dependencies (caller-owned)."""

    engine: AsyncEngine
    storage: ObjectUploader
    publisher: Publisher
    audit: ConnectorAudit
    bronze_bucket: str
    adapter: ConnectorAdapter
    connector_name: str
    pii_backend: PiiBackend | None = None

    async def run(self, trigger: ConnectorTrigger) -> ConnectorOutcome:
        """Run one trigger through the pipeline. Terminal failures return an outcome
        (the caller acks); the fresh happy path lands bronze and publishes."""
        log = _log.bind(
            stage="connector_pipeline",
            tenant_id=str(trigger.tenant_id),
            trace_id=str(trigger.trace_id),
            source_id=trigger.source_id,
        )
        lap = _Lap()

        # 1. Authenticate. Failure is terminal, no bronze row (identity known: audit
        #    it under RECEIVED with the stable reason).
        try:
            auth = self.adapter.authenticate(trigger)
        except ConnectorError as exc:
            await self._emit_terminal_failure(trigger, exc, lap)
            log.error("authenticate failed; terminal, no bronze row")
            return ConnectorOutcome("auth_failed", trigger.trace_id, None, trigger.cursor)

        # 2. Extract (cursor incremental) across the trigger's domains.
        try:
            extract = self._extract_all(auth, trigger)
        except ConnectorError as exc:
            await self._emit_terminal_failure(trigger, exc, lap)
            log.error("extract failed; terminal, no bronze row")
            return ConnectorOutcome("extract_failed", trigger.trace_id, None, trigger.cursor)

        # 3. Serialize to CSV bytes; hash exactly the bytes to be uploaded.
        data = serialize_rows(extract.header, extract.rows)
        payload_sha256 = hashlib.sha256(data).hexdigest()

        # 4. Idempotency: the dedup lookup, scoped to the api channel, before any write.
        async with rls_session(self.engine, trigger.tenant_id) as conn:
            prior = await find_prior(
                conn,
                upload_session_id=trigger.connector_run_id,
                payload_sha256=payload_sha256,
                tenant_id=str(trigger.tenant_id),
                trace_id=str(trigger.trace_id),
                dis_channel=API_CHANNEL,
            )
        if prior is not None:
            return await self._handle_duplicate(trigger, prior, lap)

        # 5. Structural preflight (the adapter's; the SDK's run_preflight is the
        #    reusable default). Failure -> FAILED bronze row, no publish.
        preflight = self.adapter.preflight(extract)
        if not preflight.ok:
            return await self._handle_preflight_failure(trigger, data, payload_sha256, preflight, lap)

        await self.audit.emit(
            stage=Stage.RECEIVED,
            outcome=Outcome.SUCCESS,
            tenant_id=trigger.tenant_id,
            trace_id=trigger.trace_id,
            row_count=preflight.row_count,
            duration_ms=lap.lap(),
            event_data={
                "preflight": {"columns": len(preflight.columns), "row_count": preflight.row_count},
                "connector_run_id": trigger.connector_run_id,
                "domains": [domain.value for domain in trigger.domains],
                **(
                    {
                        "dropped_count": extract.dropped_count,
                        "dropped_sample": list(extract.dropped_sample),
                    }
                    if extract.dropped_count
                    else {}
                ),
            },
        )

        # 6. PII gate over the CSV header, BEFORE the bronze write.
        detected = await self._gate_pii(trigger, preflight, lap)

        # 7. Upload the CSV object; the connector is the producer.
        received_at = now_utc()
        object_key = build_object_path(
            tenant_id=trigger.tenant_id,
            source_id=trigger.source_id,
            trace_id=trigger.trace_id,
            event_ts=received_at,
            ext="csv",
        )
        gcs_uri = f"gs://{self.bronze_bucket}/{object_key}"
        self.storage.upload_bytes(object_key, data, content_type=CONTENT_TYPE)

        # 8. Bronze write (metadata only) via dis-rls under the trigger's tenant.
        bronze_id = new_uuid7()
        row = BronzeRow(
            id=bronze_id,
            tenant_id=trigger.tenant_id,
            store_id=trigger.store_id,
            source_id=trigger.source_id,
            trace_id=trigger.trace_id,
            gcs_uri=gcs_uri,
            payload_size_bytes=len(data),
            payload_sha256=payload_sha256,
            row_count=preflight.row_count,
            source_payload_id=trigger.connector_run_id,
            template_id=trigger.template_id,
            original_filename=self._origin_label(trigger, received_at),
            received_at=received_at,
            processing_status="RECEIVED",
            dis_channel=API_CHANNEL,
        )
        async with rls_session(self.engine, trigger.tenant_id) as conn:
            await insert_row(conn, row)
        await self.audit.emit(
            stage=Stage.BRONZE_WRITTEN,
            outcome=Outcome.SUCCESS,
            tenant_id=trigger.tenant_id,
            trace_id=trigger.trace_id,
            bronze_id=bronze_id,
            row_count=preflight.row_count,
            duration_ms=lap.lap(),
            event_data={"pii_columns_detected": len(detected)},
        )

        # 9. Publish AFTER bronze lands, then stamp the publish.
        envelope = self._build_envelope(
            trigger, trace_id=trigger.trace_id, bronze_ref=bronze_id, gcs_uri=gcs_uri, received_at=received_at
        )
        self.publisher.publish(INGRESS_READY_TOPIC, envelope.to_bytes())
        async with rls_session(self.engine, trigger.tenant_id) as conn:
            await mark_published(conn, bronze_id=bronze_id, published_at=now_utc())
        await self.audit.emit(
            stage=Stage.INGRESS_PUBLISHED,
            outcome=Outcome.SUCCESS,
            tenant_id=trigger.tenant_id,
            trace_id=trigger.trace_id,
            bronze_id=bronze_id,
            duration_ms=lap.lap(),
            event_data={"topic": INGRESS_READY_TOPIC},
        )
        # This path EXTRACTED, so it knows the posture authoritatively: a None here is
        # "no rate-limit response this run" and CLEARS a stored throttle.
        await self._emit_health_seen(
            trigger,
            dropped_count=extract.dropped_count,
            rate_limit_state=extract.rate_limit_state,
        )
        log.info("ingested")
        return ConnectorOutcome("ingested", trigger.trace_id, bronze_id, extract.next_cursor)

    # -- extract fan-in ---------------------------------------------------------

    def _extract_all(self, auth: AuthContext, trigger: ConnectorTrigger) -> ExtractResult:
        """Extract each domain and concatenate into one table (union header).

        The next cursor is the PRIMARY (first) domain's; a multi-domain trigger shares
        one cursor slot, so the scheduler should prefer one primary domain per trigger
        for fine-grained cursors (the common Square case: one domain per trigger).
        """
        header: dict[str, None] = {}
        rows: list[ExtractRow] = []
        primary_cursor: Cursor | None = None
        dropped_count = 0
        dropped_sample: list[str] = []
        # Folded most-severe-first across domains: one trigger writes one posture, and a
        # throttle on any domain is a throttle for the run.
        rate_limit_state: str | None = None
        for index, domain in enumerate(trigger.domains):
            result = self.adapter.extract(auth, domain, trigger.cursor)
            if index == 0:
                primary_cursor = result.next_cursor
            for column in result.header:
                header.setdefault(column, None)
            rows.extend(result.rows)
            dropped_count += result.dropped_count
            dropped_sample.extend(result.dropped_sample)
            rate_limit_state = merge_rate_limit_state(rate_limit_state, result.rate_limit_state)
        return ExtractResult(
            domain=trigger.domains[0],
            header=tuple(header),
            rows=tuple(rows),
            next_cursor=primary_cursor,
            dropped_count=dropped_count,
            dropped_sample=tuple(dropped_sample[:DROPPED_SAMPLE_MAX]),
            rate_limit_state=rate_limit_state,
        )

    # -- duplicate / failure paths (mirror csv-ingest-worker) -------------------

    async def _handle_duplicate(
        self, trigger: ConnectorTrigger, prior: PriorIngest, lap: _Lap
    ) -> ConnectorOutcome:
        """Redelivery semantics: full no-op, or resume the lost publish.

        The object was already uploaded under the prior trace (the connector is the
        producer), so the resume path reuses ``prior.gcs_uri`` and does NOT re-upload;
        it re-publishes under the PRIOR trace_id and marks it (no second bronze row).
        """
        log = _log.bind(stage="idempotency", tenant_id=str(trigger.tenant_id), trace_id=str(trigger.trace_id))
        if prior.processing_status == "FAILED" or prior.is_published:
            await self.audit.emit(
                stage=Stage.RECEIVED,
                outcome=Outcome.DUPLICATE_NOOP,
                tenant_id=trigger.tenant_id,
                trace_id=trigger.trace_id,
                prior_trace_id=prior.trace_id,
                bronze_id=prior.bronze_id,
                duration_ms=lap.lap(),
                event_data={"prior_status": prior.processing_status},
            )
            await self._emit_health_seen(trigger)
            log.info("duplicate within dedup window; no-op")
            return ConnectorOutcome("duplicate_noop", prior.trace_id, prior.bronze_id, trigger.cursor)

        # Unpublished RECEIVED prior: bronze landed, the publish was lost. Complete it
        # under the PRIOR trace_id, reusing the already-uploaded object, and mark it.
        envelope = self._build_envelope(
            trigger,
            trace_id=prior.trace_id,
            bronze_ref=prior.bronze_id,
            gcs_uri=prior.gcs_uri,
            received_at=prior.received_at,
        )
        self.publisher.publish(INGRESS_READY_TOPIC, envelope.to_bytes())
        async with rls_session(self.engine, trigger.tenant_id) as conn:
            await mark_published(conn, bronze_id=prior.bronze_id, published_at=now_utc())
        await self.audit.emit(
            stage=Stage.INGRESS_PUBLISHED,
            outcome=Outcome.RETRIED,
            tenant_id=trigger.tenant_id,
            trace_id=prior.trace_id,
            bronze_id=prior.bronze_id,
            duration_ms=lap.lap(),
            event_data={"resumed": True, "topic": INGRESS_READY_TOPIC},
        )
        await self._emit_health_seen(trigger)
        log.info("duplicate with unpublished prior; publish resumed and marked")
        return ConnectorOutcome("duplicate_resumed", prior.trace_id, prior.bronze_id, trigger.cursor)

    async def _handle_preflight_failure(
        self,
        trigger: ConnectorTrigger,
        data: bytes,
        payload_sha256: str,
        preflight: PreflightResult,
        lap: _Lap,
    ) -> ConnectorOutcome:
        """Preflight failure: upload the object (so the FAILED row's gcs_uri resolves
        for ops), write a FAILED bronze row + FAILURE audit, NO publish, terminal.

        The FAILED row makes the failure durable/ops-queryable and lets the dedup absorb
        a redelivery of the same bad extract (mirrors the CSV worker).
        """
        received_at = now_utc()
        object_key = build_object_path(
            tenant_id=trigger.tenant_id,
            source_id=trigger.source_id,
            trace_id=trigger.trace_id,
            event_ts=received_at,
            ext="csv",
        )
        gcs_uri = f"gs://{self.bronze_bucket}/{object_key}"
        self.storage.upload_bytes(object_key, data, content_type=CONTENT_TYPE)

        bronze_id = new_uuid7()
        row = BronzeRow(
            id=bronze_id,
            tenant_id=trigger.tenant_id,
            store_id=trigger.store_id,
            source_id=trigger.source_id,
            trace_id=trigger.trace_id,
            gcs_uri=gcs_uri,
            payload_size_bytes=len(data),
            payload_sha256=payload_sha256,
            row_count=None,
            source_payload_id=trigger.connector_run_id,
            template_id=trigger.template_id,
            original_filename=self._origin_label(trigger, received_at),
            received_at=received_at,
            processing_status="FAILED",
            dis_channel=API_CHANNEL,
        )
        async with rls_session(self.engine, trigger.tenant_id) as conn:
            await insert_row(conn, row)
        reason = preflight.reason
        assert reason is not None  # not ok implies a reason (preflight contract)
        await self.audit.emit(
            stage=Stage.RECEIVED,
            outcome=Outcome.FAILURE,
            tenant_id=trigger.tenant_id,
            trace_id=trigger.trace_id,
            bronze_id=bronze_id,
            duration_ms=lap.lap(),
            failure_code=failure_code_for_reason(reason),
            failure_message=f"connector preflight failed: {reason.value}",
            event_data={"preflight_failed": True, "reason": reason.value, "detail": preflight.detail},
        )
        await self._emit_health_error(trigger, detail=reason.value)
        _log.bind(stage="preflight", tenant_id=str(trigger.tenant_id), trace_id=str(trigger.trace_id)).error(
            "connector preflight failed; FAILED bronze row written, no publish"
        )
        return ConnectorOutcome("preflight_failed", trigger.trace_id, bronze_id, trigger.cursor)

    async def _gate_pii(
        self, trigger: ConnectorTrigger, preflight: PreflightResult, lap: _Lap
    ) -> frozenset[str]:
        """The fail-loud PII gate over the CSV header, BEFORE the bronze write.

        v1.0 has no backend, so a detected column raises; the FAILURE audit fires before
        the re-raise (identifiers/counts only, never names or values).
        """
        try:
            detected = gate_csv_headers(
                list(preflight.columns),
                tenant_id=str(trigger.tenant_id),
                trace_id=str(trigger.trace_id),
                backend=self.pii_backend,
            )
        except Exception as exc:
            from dis_audit import failure_code_for
            from dis_core.errors import PiiBackendNotConfiguredError

            event_data: dict[str, object] = {"exception_class": type(exc).__name__}
            if isinstance(exc, PiiBackendNotConfiguredError):
                event_data["pii_columns_detected"] = len(exc.columns)
            await self.audit.emit(
                stage=Stage.PII_TOKENIZED,
                outcome=Outcome.FAILURE,
                tenant_id=trigger.tenant_id,
                trace_id=trigger.trace_id,
                duration_ms=lap.lap(),
                failure_code=failure_code_for(exc),
                failure_message=str(exc),
                event_data=event_data,
            )
            raise
        await self.audit.emit(
            stage=Stage.PII_TOKENIZED,
            outcome=Outcome.SUCCESS,
            tenant_id=trigger.tenant_id,
            trace_id=trigger.trace_id,
            duration_ms=lap.lap(),
            event_data={
                "pii_columns_detected": len(detected),
                "backend_configured": self.pii_backend is not None,
            },
        )
        return detected

    # -- helpers ----------------------------------------------------------------

    def _build_envelope(
        self,
        trigger: ConnectorTrigger,
        *,
        trace_id: UUID,
        bronze_ref: UUID,
        gcs_uri: str,
        received_at: datetime,
    ) -> IngressReadyEnvelope:
        """Construct the frozen ingress.ready envelope from the trigger + bronze row.

        ``delimiter`` is set to the comma the connector serialized with (the consumer
        reads it off the envelope; no downstream detection). ``build_ingress_ready`` is
        not reused because it is typed to a CsvReceivedEvent (us_-patterned session id)."""
        return IngressReadyEnvelope(
            trace_id=trace_id,
            tenant_id=trigger.tenant_id,
            store_id=trigger.store_id,
            source_id=trigger.source_id,
            template_id=trigger.template_id,
            bronze_ref=bronze_ref,
            gcs_uri=gcs_uri,
            received_ts=ensure_utc(received_at),
            delimiter=DELIMITER,
            tenant_display_code=trigger.tenant_display_code,
            store_code=trigger.store_code,
            replay=False,
            parent_trace_id=None,
        )

    def _origin_label(self, trigger: ConnectorTrigger, received_at: datetime) -> str:
        """The bronze ``original_filename`` display label: ``{connector}:{stream}:{iso}``."""
        stream = "+".join(domain.value for domain in trigger.domains)
        return f"{self.connector_name}:{stream}:{received_at.isoformat()}"

    # -- connector-health emit: additive + fire-and-forget -----------------------

    async def _emit_terminal_failure(self, trigger: ConnectorTrigger, exc: ConnectorError, lap: _Lap) -> None:
        """Audit a terminal (pre-bronze) failure + stamp connector-health error."""
        await self.audit.emit(
            stage=Stage.RECEIVED,
            outcome=Outcome.FAILURE,
            tenant_id=trigger.tenant_id,
            trace_id=trigger.trace_id,
            duration_ms=lap.lap(),
            failure_code=failure_code_for_reason(exc.reason),
            failure_message=str(exc),
            event_data={"reason": exc.reason.value, "detail": exc.detail},
        )
        # The retry budget ran out on a vendor rate limit: that IS the posture, stamped off
        # the error (there is no ExtractResult to carry it). Any other reason leaves the
        # stored posture alone - a failure for another cause says nothing about throttling.
        rate_limit_state: RateLimitState = (
            RATE_LIMIT_EXHAUSTED if exc.reason is ConnectorReasonCode.RATE_LIMITED else RATE_LIMIT_UNKNOWN
        )
        await self._emit_health_error(trigger, detail=exc.reason.value, rate_limit_state=rate_limit_state)

    async def _emit_health_seen(
        self,
        trigger: ConnectorTrigger,
        *,
        dropped_count: int = 0,
        rate_limit_state: RateLimitState = RATE_LIMIT_UNKNOWN,
    ) -> None:
        """Stamp a successful arrival on telemetry.connector_health (best-effort).

        ``dropped_count`` (>0) rides the health metadata as a coarse hint for the health
        surface; the full detail (the sku_id sample) lives on the RECEIVED audit, not here.

        ``rate_limit_state`` defaults to preserve: the duplicate no-op paths reach here
        without having extracted, so they genuinely do not know the posture. The ingest
        path passes what it observed.
        """
        metadata = {"dropped_count": dropped_count} if dropped_count else None
        try:
            async with rls_session(self.engine, trigger.tenant_id) as conn:
                await upsert_health_seen(
                    conn,
                    tenant_id=trigger.tenant_id,
                    source_id=trigger.source_id,
                    metadata=metadata,
                    rate_limit_state=rate_limit_state,
                )
        except _TRANSIENT_DB_ERRORS:
            # Tier 1: a transient DB blip. Warn and swallow (telemetry never blocks ingest).
            _log.bind(
                stage="connector_health",
                tenant_id=str(trigger.tenant_id),
                trace_id=str(trigger.trace_id),
                source_id=trigger.source_id,
            ).warning("connector-health seen-emit failed; ingest unaffected (fire-and-forget)")
        except Exception:  # noqa: BLE001 - telemetry never blocks ingest
            # Tier 2: anything else reaching here is a PROGRAMMING error (TypeError,
            # AttributeError, KeyError, bad SQL). Still swallowed - the behaviour is
            # right, a broken emit must not block ingest - but logged at ERROR with a
            # traceback under a `bug` marker so it is findable rather than hiding
            # behind a green test board.
            _log.bind(
                stage="connector_health",
                tenant_id=str(trigger.tenant_id),
                trace_id=str(trigger.trace_id),
                source_id=trigger.source_id,
                bug=True,
            ).exception("BUG: connector-health seen-emit raised a non-transient error; swallowed")

    async def _emit_health_error(
        self,
        trigger: ConnectorTrigger,
        *,
        detail: str,
        rate_limit_state: RateLimitState = RATE_LIMIT_UNKNOWN,
    ) -> None:
        """Stamp a failed run on telemetry.connector_health (best-effort, same posture).

        ``rate_limit_state`` defaults to preserve; only the rate-limit failure itself
        (via ``_emit_terminal_failure``) passes a value. A preflight failure, for
        instance, says nothing about throttling.
        """
        try:
            async with rls_session(self.engine, trigger.tenant_id) as conn:
                await upsert_health_error(
                    conn,
                    tenant_id=trigger.tenant_id,
                    source_id=trigger.source_id,
                    detail=detail,
                    rate_limit_state=rate_limit_state,
                )
        except _TRANSIENT_DB_ERRORS:
            # Tier 1: a transient DB blip. Warn and swallow (telemetry never blocks ingest).
            _log.bind(
                stage="connector_health",
                tenant_id=str(trigger.tenant_id),
                trace_id=str(trigger.trace_id),
                source_id=trigger.source_id,
            ).warning("connector-health error-emit failed; ingest unaffected (fire-and-forget)")
        except Exception:  # noqa: BLE001 - telemetry never blocks ingest
            # Tier 2: a PROGRAMMING error. Swallowed, but ERROR + traceback + `bug`
            # marker so it surfaces. See the seen-emit twin above.
            _log.bind(
                stage="connector_health",
                tenant_id=str(trigger.tenant_id),
                trace_id=str(trigger.trace_id),
                source_id=trigger.source_id,
                bug=True,
            ).exception("BUG: connector-health error-emit raised a non-transient error; swallowed")
