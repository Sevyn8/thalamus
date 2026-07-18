"""Connector-health emit unit surface (D116): the upsert shape + the fire-and-forget posture.

The SQL is proven against the live schema (WITH CHECK isolation, the ON CONFLICT) by the
integration suite; here the pure logic is pinned: ``upsert_health_seen``/``upsert_health_error``
issue a single idempotent ``INSERT ... ON CONFLICT (tenant_id, source_id) DO UPDATE`` with the
right coarse status and the right stamped columns (seen touches last_seen_at, error touches the
error fields — neither clobbers the other's), and the pipeline's ``_emit_health_*`` helpers are
ADDITIVE + FIRE-AND-FORGET: a failing health write is swallowed, never raised into the data path.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from csv_ingest_worker import pipeline as pipeline_module
from csv_ingest_worker.connector_health import (
    STATUS_HEALTHY,
    STATUS_STALE,
    upsert_health_error,
    upsert_health_seen,
)
from csv_ingest_worker.pipeline import IngestPipeline

_TENANT = UUID("019e5e3c-b5d3-705f-9002-2451c4ca2626")  # buc-ees
_SOURCE = "manual_csv_upload"
_TRACE = UUID("019e8d88-4e76-7911-bb77-d8fcba1808a6")


def _event() -> Any:
    """A minimal stand-in carrying just the fields the health emit reads."""
    return SimpleNamespace(tenant_id=_TENANT, source_id=_SOURCE, trace_id=_TRACE)


def _min_pipeline() -> IngestPipeline:
    """A pipeline whose non-DB seams are never touched by the health emit."""
    return IngestPipeline(
        engine=object(),  # type: ignore[arg-type]  # rls_session is faked in these tests
        storage=object(),  # type: ignore[arg-type]
        publisher=object(),  # type: ignore[arg-type]
        audit=object(),  # type: ignore[arg-type]
        bronze_bucket="b",
    )


class _RecordingConnection:
    """Captures the executed statement text + params (the upsert-shape probe)."""

    def __init__(self) -> None:
        self.sql: str = ""
        self.params: dict[str, Any] = {}

    async def execute(self, statement: Any, params: dict[str, Any]) -> None:
        self.sql = str(statement)
        self.params = params


async def test_seen_upsert_shape_and_status() -> None:
    conn = _RecordingConnection()
    await upsert_health_seen(conn, tenant_id=_TENANT, source_id=_SOURCE)  # type: ignore[arg-type]
    sql = conn.sql.lower()
    assert "insert into telemetry.connector_health" in sql
    assert "on conflict (tenant_id, source_id) do update" in sql
    assert "last_seen_at = excluded.last_seen_at" in sql
    # A healthy re-run must NOT clear a prior error record: seen does not stamp error columns.
    assert "last_error_at" not in sql
    assert conn.params["tenant_id"] == _TENANT
    assert conn.params["source_id"] == _SOURCE
    assert conn.params["status"] == STATUS_HEALTHY


async def test_error_upsert_shape_status_and_detail() -> None:
    conn = _RecordingConnection()
    await upsert_health_error(conn, tenant_id=_TENANT, source_id=_SOURCE, detail="not_csv")  # type: ignore[arg-type]
    sql = conn.sql.lower()
    assert "insert into telemetry.connector_health" in sql
    assert "on conflict (tenant_id, source_id) do update" in sql
    assert "last_error_at = excluded.last_error_at" in sql
    assert "last_error_detail = excluded.last_error_detail" in sql
    # Error stamp must NOT clobber last_seen_at (a prior success stays visible).
    assert "last_seen_at" not in sql
    assert conn.params["status"] == STATUS_STALE
    assert conn.params["detail"] == "not_csv"


# -- pipeline emit: additive + fire-and-forget --------------------------------------


async def test_emit_seen_calls_upsert_under_the_event_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_rls_session(engine: Any, tenant_id: Any) -> AsyncIterator[Any]:
        captured["session_tenant"] = tenant_id
        yield object()

    async def fake_upsert(conn: Any, *, tenant_id: UUID, source_id: str) -> None:
        captured["tenant_id"] = tenant_id
        captured["source_id"] = source_id

    monkeypatch.setattr(pipeline_module, "rls_session", fake_rls_session)
    monkeypatch.setattr(pipeline_module, "upsert_health_seen", fake_upsert)
    await _min_pipeline()._emit_health_seen(_event())
    # The write rides an rls_session under the EVENT's tenant (WITH CHECK backstop).
    assert captured["session_tenant"] == _TENANT
    assert captured["tenant_id"] == _TENANT
    assert captured["source_id"] == _SOURCE


async def test_emit_seen_is_fire_and_forget(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def exploding_rls_session(engine: Any, tenant_id: Any) -> AsyncIterator[Any]:
        raise RuntimeError("injected connector-health write failure")
        yield  # pragma: no cover

    monkeypatch.setattr(pipeline_module, "rls_session", exploding_rls_session)
    # A failing health write must NOT raise into the data path (fire-and-forget, D116).
    await _min_pipeline()._emit_health_seen(_event())


async def test_emit_error_is_fire_and_forget(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def exploding_rls_session(engine: Any, tenant_id: Any) -> AsyncIterator[Any]:
        raise RuntimeError("injected connector-health write failure")
        yield  # pragma: no cover

    monkeypatch.setattr(pipeline_module, "rls_session", exploding_rls_session)
    await _min_pipeline()._emit_health_error(_event(), detail="not_csv")
