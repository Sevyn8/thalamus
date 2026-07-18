"""ConnectorPipeline orchestration: ordering, dispositions, and the trust boundary.

All DB seams (rls_session / find_prior / insert_row / mark_published / health upserts)
are monkeypatched with recorders so the ORDER of effects is assertable without a
database: dedup before compute, PII before the bronze write, upload before insert,
insert before publish, publish before mark (mirrors the csv-ingest-worker pipeline test).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import pytest

import thalamus_connector_sdk.pipeline as pipeline_module
from dis_audit import AuditEvent, Stage
from thalamus_connector_sdk import (
    AuthContext,
    ConnectorAudit,
    ConnectorAuthError,
    ConnectorPipeline,
    ConnectorReasonCode,
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
_TEMPLATE = UUID("019e93f0-57ca-7470-9899-ba6532ff1600")
_RUN_ID = "run_square_0001"
_BUCKET = "ithina-bronze-raw"
_HEADER = ("sku_id", "product_name", "current_retail_price", "currency", "stock_qty")


def _rows() -> tuple[ExtractRow, ...]:
    return (
        ExtractRow(
            {
                "sku_id": "A-1",
                "product_name": "Widget",
                "current_retail_price": "9.99",
                "currency": "USD",
                "stock_qty": "42",
            }
        ),
    )


def _trigger(**overrides: Any) -> ConnectorTrigger:
    base: dict[str, Any] = {
        "schema_version": 1,
        "trace_id": _TRACE,
        "connector_run_id": _RUN_ID,
        "tenant_id": _TENANT,
        "store_id": _STORE,
        "source_id": "square_pos",
        "template_id": _TEMPLATE,
        "domains": [Domain.CATALOG],
        "cursor": "cursor-in",
    }
    base.update(overrides)
    return ConnectorTrigger(**base)


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def add(self, name: str, payload: Any = None) -> None:
        self.calls.append((name, payload))

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def first(self, name: str) -> Any:
        return next(payload for n, payload in self.calls if n == name)


class _FakeUploader:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    def upload_bytes(self, object_path: str, data: bytes, *, content_type: str | None = None) -> None:
        self._recorder.add("upload", (object_path, content_type, data))


class _FakePublisher:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    def publish(self, topic_name: str, data: bytes) -> str:
        self._recorder.add("publish", (topic_name, json.loads(data)))
        return "msg-1"


class _RecordingAuditWriter:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder
        self.events: list[AuditEvent] = []

    async def write(self, event: AuditEvent) -> bool:
        self.events.append(event)
        self._recorder.add("audit", (event.stage, event.outcome))
        self._recorder.add("audit_data", (event.stage, event.event_data))
        return True


class _FakeAdapter:
    """A ConnectorAdapter fake: canned auth/extract, real structural preflight."""

    def __init__(
        self,
        *,
        header: tuple[str, ...] = _HEADER,
        rows: tuple[ExtractRow, ...] | None = None,
        auth_error: ConnectorAuthError | None = None,
        next_cursor: str | None = "cursor-out",
        dropped_count: int = 0,
        dropped_sample: tuple[str, ...] = (),
    ) -> None:
        self._header = header
        self._rows = _rows() if rows is None else rows
        self._auth_error = auth_error
        self._next_cursor = next_cursor
        self._dropped_count = dropped_count
        self._dropped_sample = dropped_sample

    def authenticate(self, trigger: ConnectorTrigger) -> AuthContext:
        if self._auth_error is not None:
            raise self._auth_error
        return AuthContext(token="tok")

    def discover(self, auth: AuthContext) -> Discovery:
        return Discovery(locations=(), native_schema={})

    def extract(self, auth: AuthContext, domain: Domain, cursor: str | None) -> ExtractResult:
        return ExtractResult(
            domain=domain,
            header=self._header,
            rows=self._rows,
            next_cursor=self._next_cursor,
            dropped_count=self._dropped_count,
            dropped_sample=self._dropped_sample,
        )

    def preflight(self, extract: ExtractResult) -> PreflightResult:
        return run_preflight(extract)


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    recorder: _Recorder,
    *,
    adapter: _FakeAdapter,
    prior: Any = None,
) -> ConnectorPipeline:
    @asynccontextmanager
    async def fake_rls_session(engine: Any, tenant_id: Any) -> AsyncIterator[Any]:
        recorder.add("rls_session", str(tenant_id))
        yield object()

    async def fake_find_prior(conn: Any, **kwargs: Any) -> Any:
        recorder.add("find_prior", kwargs)
        return prior

    async def fake_insert_row(conn: Any, row: Any) -> None:
        recorder.add("insert", row)

    async def fake_mark_published(conn: Any, *, bronze_id: UUID, published_at: Any) -> None:
        recorder.add("mark_published", bronze_id)

    async def fake_health_seen(
        conn: Any, *, tenant_id: UUID, source_id: str, metadata: dict[str, Any] | None = None
    ) -> None:
        recorder.add("health_seen", metadata)

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
        engine=object(),  # type: ignore[arg-type]  # never touched: rls_session is faked
        storage=_FakeUploader(recorder),
        publisher=_FakePublisher(recorder),
        audit=ConnectorAudit(_RecordingAuditWriter(recorder), service_name="thalamus-square-test"),
        bronze_bucket=_BUCKET,
        adapter=adapter,
        connector_name="square",
    )


async def test_happy_path_lands_bronze_then_publishes() -> None:
    monkeypatch = pytest.MonkeyPatch()
    recorder = _Recorder()
    pipeline = _wire(monkeypatch, recorder, adapter=_FakeAdapter())
    try:
        outcome = await pipeline.run(_trigger())
    finally:
        monkeypatch.undo()

    assert outcome.disposition == "ingested"
    assert outcome.bronze_id is not None
    assert outcome.next_cursor == "cursor-out"

    names = recorder.names()
    # Ordering: dedup -> upload -> insert -> publish -> mark.
    assert names.index("find_prior") < names.index("upload")
    assert names.index("upload") < names.index("insert")
    assert names.index("insert") < names.index("publish")
    assert names.index("publish") < names.index("mark_published")


async def test_dedup_lookup_is_api_channel_keyed_on_connector_run_id() -> None:
    monkeypatch = pytest.MonkeyPatch()
    recorder = _Recorder()
    pipeline = _wire(monkeypatch, recorder, adapter=_FakeAdapter())
    try:
        await pipeline.run(_trigger())
    finally:
        monkeypatch.undo()
    kwargs = recorder.first("find_prior")
    assert kwargs["upload_session_id"] == _RUN_ID  # source_payload_id = connector_run_id
    assert kwargs["dis_channel"] == "api"


async def test_dropped_count_surfaces_on_received_audit_and_health() -> None:
    monkeypatch = pytest.MonkeyPatch()
    recorder = _Recorder()
    adapter = _FakeAdapter(dropped_count=3, dropped_sample=("SKU-A", "SKU-B"))
    pipeline = _wire(monkeypatch, recorder, adapter=adapter)
    try:
        await pipeline.run(_trigger())
    finally:
        monkeypatch.undo()

    received = next(
        payload[1]
        for name, payload in recorder.calls
        if name == "audit_data" and payload[0] is Stage.RECEIVED
    )
    assert received is not None
    assert received["dropped_count"] == 3
    assert received["dropped_sample"] == ["SKU-A", "SKU-B"]
    # The health seen-emit still fires (metadata hint is best-effort, count-only).
    assert "health_seen" in recorder.names()


async def test_bronze_and_object_carry_api_csv_and_read_trace() -> None:
    monkeypatch = pytest.MonkeyPatch()
    recorder = _Recorder()
    pipeline = _wire(monkeypatch, recorder, adapter=_FakeAdapter())
    try:
        await pipeline.run(_trigger())
    finally:
        monkeypatch.undo()

    row = recorder.first("insert")
    assert row.dis_channel == "api"
    assert row.source_payload_id == _RUN_ID
    assert row.trace_id == _TRACE  # READ off the trigger, never minted
    assert row.original_filename.startswith("square:CATALOG:")

    object_path, content_type, data = recorder.first("upload")
    assert object_path.endswith(".csv")
    assert content_type == "text/csv"
    assert data.startswith(b"sku_id,product_name,current_retail_price,currency,stock_qty")

    _topic, envelope = recorder.first("publish")
    assert envelope["delimiter"] == ","
    assert envelope["gcs_uri"].endswith(".csv")
    assert envelope["trace_id"] == str(_TRACE)


async def test_preflight_empty_extract_fails_without_publish() -> None:
    monkeypatch = pytest.MonkeyPatch()
    recorder = _Recorder()
    pipeline = _wire(monkeypatch, recorder, adapter=_FakeAdapter(rows=()))
    try:
        outcome = await pipeline.run(_trigger())
    finally:
        monkeypatch.undo()

    assert outcome.disposition == "preflight_failed"
    names = recorder.names()
    assert "insert" in names  # a FAILED bronze row lands
    assert "publish" not in names  # write-then-conditionally-publish (D5)
    assert "health_error" in names
    failed_row = recorder.first("insert")
    assert failed_row.processing_status == "FAILED"


async def test_auth_failure_is_terminal_no_bronze() -> None:
    monkeypatch = pytest.MonkeyPatch()
    recorder = _Recorder()
    adapter = _FakeAdapter(auth_error=ConnectorAuthError("bad token", reason=ConnectorReasonCode.AUTH_FAILED))
    pipeline = _wire(monkeypatch, recorder, adapter=adapter)
    try:
        outcome = await pipeline.run(_trigger())
    finally:
        monkeypatch.undo()

    assert outcome.disposition == "auth_failed"
    assert outcome.bronze_id is None
    names = recorder.names()
    assert "insert" not in names
    assert "publish" not in names
    assert "health_error" in names
