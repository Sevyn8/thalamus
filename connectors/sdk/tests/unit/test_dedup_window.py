"""Dedup dispositions (D58/D59): the prior-row branches the connector shares with
csv-ingest-worker.

The 24h WINDOW comparison itself lives in ``csv_ingest_worker.bronze.find_prior`` (proven
there); here the CONNECTOR's use of it is pinned: a concluded prior is a full no-op that
returns the prior trace, and an unpublished RECEIVED prior is resumed-and-marked WITHOUT a
second bronze row or a re-upload (the connector already produced the object).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

import thalamus_connector_sdk.pipeline as pipeline_module
from csv_ingest_worker.bronze import PriorIngest
from dis_audit import AuditEvent
from thalamus_connector_sdk import (
    AuthContext,
    ConnectorAudit,
    ConnectorPipeline,
    ConnectorTrigger,
    Discovery,
    Domain,
    ExtractResult,
    ExtractRow,
    PreflightResult,
    run_preflight,
)

_TENANT = UUID("019e5e3c-b5d3-705f-9002-2451c4ca2626")
_STORE = UUID("019e5e3c-b5d3-705f-9002-2451c4ca2700")
_TRACE = UUID("019e8d88-4e76-7911-bb77-d8fcba1808a6")
_PRIOR_TRACE = UUID("019e8d88-4e76-7911-bb77-d8fcba180000")
_PRIOR_BRONZE = UUID("019e93f0-57ca-7470-9899-ba6532ff15e1")
_TEMPLATE = UUID("019e93f0-57ca-7470-9899-ba6532ff1600")
_BUCKET = "ithina-bronze-raw"
_HEADER = ("sku_id", "product_name", "current_retail_price")


def _trigger() -> ConnectorTrigger:
    return ConnectorTrigger(
        schema_version=1,
        trace_id=_TRACE,
        connector_run_id="run_square_0001",
        tenant_id=_TENANT,
        store_id=_STORE,
        source_id="square_pos",
        template_id=_TEMPLATE,
        domains=[Domain.CATALOG],
        cursor="cursor-in",
    )


def _prior(**overrides: Any) -> PriorIngest:
    base: dict[str, Any] = {
        "bronze_id": _PRIOR_BRONZE,
        "trace_id": _PRIOR_TRACE,
        "store_id": _STORE,
        "source_id": "square_pos",
        "gcs_uri": "gs://ithina-bronze-raw/tenant/x/source/square_pos/yyyy=2026/mm=07/dd=18/p.csv",
        "received_at": datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
        "published_at": None,
        "processing_status": "RECEIVED",
    }
    base.update(overrides)
    return PriorIngest(**base)


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def add(self, name: str, payload: Any = None) -> None:
        self.calls.append((name, payload))

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


class _FakeUploader:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    def upload_bytes(self, object_path: str, data: bytes, *, content_type: str | None = None) -> None:
        self._recorder.add("upload", object_path)


class _FakePublisher:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    def publish(self, topic_name: str, data: bytes) -> str:
        self._recorder.add("publish", data)
        return "msg-1"


class _RecordingAuditWriter:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    async def write(self, event: AuditEvent) -> bool:
        self._recorder.add("audit", (event.stage, event.outcome, event.prior_trace_id))
        return True


class _FakeAdapter:
    def authenticate(self, trigger: ConnectorTrigger) -> AuthContext:
        return AuthContext(token="tok")

    def discover(self, auth: AuthContext) -> Discovery:
        return Discovery(locations=(), native_schema={})

    def extract(self, auth: AuthContext, domain: Domain, cursor: str | None) -> ExtractResult:
        return ExtractResult(
            domain=domain,
            header=_HEADER,
            rows=(ExtractRow({"sku_id": "A-1", "product_name": "W", "current_retail_price": "1.00"}),),
            next_cursor="cursor-out",
        )

    def preflight(self, extract: ExtractResult) -> PreflightResult:
        return run_preflight(extract)


def _wire(monkeypatch: pytest.MonkeyPatch, recorder: _Recorder, *, prior: PriorIngest) -> ConnectorPipeline:
    @asynccontextmanager
    async def fake_rls_session(engine: Any, tenant_id: Any) -> AsyncIterator[Any]:
        yield object()

    async def fake_find_prior(conn: Any, **kwargs: Any) -> PriorIngest:
        return prior

    async def fake_insert_row(conn: Any, row: Any) -> None:
        recorder.add("insert", row)

    async def fake_mark_published(conn: Any, *, bronze_id: UUID, published_at: Any) -> None:
        recorder.add("mark_published", bronze_id)

    async def fake_health_seen(
        conn: Any, *, tenant_id: UUID, source_id: str, metadata: dict[str, Any] | None = None
    ) -> None:
        recorder.add("health_seen", source_id)

    async def fake_health_error(
        conn: Any,
        *,
        tenant_id: UUID,
        source_id: str,
        detail: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        recorder.add("health_error", detail)

    monkeypatch.setattr(pipeline_module, "rls_session", fake_rls_session)
    monkeypatch.setattr(pipeline_module, "find_prior", fake_find_prior)
    monkeypatch.setattr(pipeline_module, "insert_row", fake_insert_row)
    monkeypatch.setattr(pipeline_module, "mark_published", fake_mark_published)
    monkeypatch.setattr(pipeline_module, "upsert_health_seen", fake_health_seen)
    monkeypatch.setattr(pipeline_module, "upsert_health_error", fake_health_error)

    return ConnectorPipeline(
        engine=object(),  # type: ignore[arg-type]
        storage=_FakeUploader(recorder),
        publisher=_FakePublisher(recorder),
        audit=ConnectorAudit(_RecordingAuditWriter(recorder), service_name="test"),
        bronze_bucket=_BUCKET,
        adapter=_FakeAdapter(),
        connector_name="square",
    )


async def test_published_prior_is_full_no_op_returning_prior_trace() -> None:
    monkeypatch = pytest.MonkeyPatch()
    recorder = _Recorder()
    published_prior = _prior(
        processing_status="PUBLISHED", published_at=datetime(2026, 7, 18, 9, 1, tzinfo=UTC)
    )
    pipeline = _wire(monkeypatch, recorder, prior=published_prior)
    try:
        outcome = await pipeline.run(_trigger())
    finally:
        monkeypatch.undo()

    assert outcome.disposition == "duplicate_noop"
    assert outcome.trace_id == _PRIOR_TRACE  # returns the PRIOR trace, not the trigger's
    names = recorder.names()
    assert "insert" not in names  # no second bronze row
    assert "publish" not in names  # no second publish
    assert "upload" not in names  # no re-upload


async def test_unpublished_received_prior_resumes_without_second_row_or_reupload() -> None:
    monkeypatch = pytest.MonkeyPatch()
    recorder = _Recorder()
    pipeline = _wire(monkeypatch, recorder, prior=_prior(processing_status="RECEIVED"))
    try:
        outcome = await pipeline.run(_trigger())
    finally:
        monkeypatch.undo()

    assert outcome.disposition == "duplicate_resumed"
    assert outcome.trace_id == _PRIOR_TRACE
    names = recorder.names()
    assert "insert" not in names  # resume-and-mark: no second bronze row
    assert "upload" not in names  # object already produced under the prior trace
    assert names.index("publish") < names.index("mark_published")


async def test_failed_prior_is_no_op() -> None:
    monkeypatch = pytest.MonkeyPatch()
    recorder = _Recorder()
    pipeline = _wire(monkeypatch, recorder, prior=_prior(processing_status="FAILED"))
    try:
        outcome = await pipeline.run(_trigger())
    finally:
        monkeypatch.undo()

    assert outcome.disposition == "duplicate_noop"
    assert "publish" not in recorder.names()
