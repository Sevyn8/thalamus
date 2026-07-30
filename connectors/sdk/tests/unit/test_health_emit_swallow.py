"""The two-tier swallow on the connector-health emits (L3).

Both emits stay fire-and-forget: NOTHING propagates, because a telemetry write must
never kill an ingest run that has already written bronze and published ingress.ready
(D116, hard rule 11). What changed is the CATCH, which used to be one bare
``except Exception`` and therefore absorbed a TypeError exactly as quietly as a
transient DB blip. That is how a broken duplicate-path emit hid for weeks behind a
green test board.

Tier 1 (transient DB): WARNING, swallowed, message text unchanged.
Tier 2 (anything else): ERROR with a traceback and a ``bug=True`` field, swallowed.

These tests assert the tier SELECTION and the non-propagation. They deliberately do
not assert the SQL - that is test_health_rate_limit.py's job.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.exc import OperationalError

import thalamus_connector_sdk.pipeline as pipeline_module
from thalamus_connector_sdk import (
    ConnectorAudit,
    ConnectorPipeline,
    ConnectorTrigger,
    Domain,
)

_TENANT = UUID("019e5e3c-b5d3-705f-9002-2451c4ca2626")
_STORE = UUID("019e5e3c-b5d3-705f-9002-2451c4ca2700")
_TRACE = UUID("019e8d88-4e76-7911-bb77-d8fcba1808a6")
_TEMPLATE = UUID("019e93f0-57ca-7470-9899-ba6532ff1600")

_TRANSIENT = OperationalError("SELECT 1", {}, Exception("server closed the connection"))
_PROGRAMMING = TypeError("upsert_health_seen() got an unexpected keyword argument 'metdata'")


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
        cursor=None,
    )


class _NullAuditWriter:
    async def write(self, event: Any) -> bool:
        return True


def _pipeline(monkeypatch: pytest.MonkeyPatch, *, raises: BaseException) -> ConnectorPipeline:
    """A pipeline whose health upserts both raise ``raises``."""

    @asynccontextmanager
    async def fake_rls_session(engine: Any, tenant_id: Any) -> AsyncIterator[Any]:
        yield object()

    async def boom(*args: Any, **kwargs: Any) -> None:
        raise raises

    monkeypatch.setattr(pipeline_module, "rls_session", fake_rls_session)
    monkeypatch.setattr(pipeline_module, "upsert_health_seen", boom)
    monkeypatch.setattr(pipeline_module, "upsert_health_error", boom)

    return ConnectorPipeline(
        engine=object(),  # type: ignore[arg-type]  # never touched: rls_session is faked
        storage=object(),  # type: ignore[arg-type]  # the emit path never uploads
        publisher=object(),  # type: ignore[arg-type]  # the emit path never publishes
        audit=ConnectorAudit(_NullAuditWriter(), service_name="thalamus-square-test"),
        bronze_bucket="ithina-bronze-raw",
        adapter=object(),  # type: ignore[arg-type]  # the emit path never extracts
        connector_name="square",
    )


@pytest.mark.parametrize("emit", ["seen", "error"])
async def test_transient_db_error_warns_and_is_swallowed(
    emit: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """LOAD-BEARING: a DB blip must NOT kill an ingest run and must NOT read as a bug."""
    pipeline = _pipeline(monkeypatch, raises=_TRANSIENT)
    caplog.set_level("DEBUG")

    if emit == "seen":
        await pipeline._emit_health_seen(_trigger())
    else:
        await pipeline._emit_health_error(_trigger(), detail="PREFLIGHT_FAILED")

    records = [r for r in caplog.records if "connector-health" in r.getMessage()]
    assert len(records) == 1
    assert records[0].levelname == "WARNING"
    assert records[0].exc_info is None
    assert not getattr(records[0], "bug", False)
    # Message text is byte-identical to what shipped before the tier split; queries
    # depend on it.
    assert records[0].getMessage() == (
        f"connector-health {emit}-emit failed; ingest unaffected (fire-and-forget)"
    )


@pytest.mark.parametrize("emit", ["seen", "error"])
async def test_programming_error_logs_bug_at_error_and_is_swallowed(
    emit: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """LOAD-BEARING: the class that hid the last bug now surfaces, still without
    blocking ingest. A TypeError must reach ERROR with a traceback and the ``bug``
    marker; if this regresses to WARNING (or to the tier-1 tuple), a broken emit goes
    invisible again."""
    pipeline = _pipeline(monkeypatch, raises=_PROGRAMMING)
    caplog.set_level("DEBUG")

    if emit == "seen":
        await pipeline._emit_health_seen(_trigger())
    else:
        await pipeline._emit_health_error(_trigger(), detail="PREFLIGHT_FAILED")

    records = [r for r in caplog.records if "connector-health" in r.getMessage()]
    assert len(records) == 1
    assert records[0].levelname == "ERROR"
    assert records[0].exc_info is not None
    assert getattr(records[0], "bug", None) is True
    assert records[0].getMessage().startswith("BUG:")


@pytest.mark.parametrize("raises", [_TRANSIENT, _PROGRAMMING], ids=["transient", "programming"])
@pytest.mark.parametrize("emit", ["seen", "error"])
async def test_nothing_propagates_from_either_tier(
    emit: str, raises: BaseException, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D116 / hard rule 11 still holds: neither tier re-raises."""
    pipeline = _pipeline(monkeypatch, raises=raises)

    if emit == "seen":
        await pipeline._emit_health_seen(_trigger())
    else:
        await pipeline._emit_health_error(_trigger(), detail="PREFLIGHT_FAILED")
