"""Unit tests for the structured logging helper."""

from __future__ import annotations

import io
import json
import logging
from typing import Any

import pytest

from dis_core.logging import DisLoggerAdapter, configure_logging, get_logger

try:
    from pythonjsonlogger.json import JsonFormatter
except ImportError:  # 2.x (see dis_core.logging — the 3.x stubs don't re-export this name)
    from pythonjsonlogger.jsonlogger import JsonFormatter  # type: ignore[attr-defined]


def test_get_logger_binds_service() -> None:
    log = get_logger("streaming-consumer")
    assert isinstance(log, DisLoggerAdapter)
    assert log.extra is not None  # LoggerAdapter.extra is Optional; ours always binds it
    assert log.extra["service"] == "streaming-consumer"


def test_bind_adds_context_without_mutating_parent() -> None:
    parent = get_logger("dis-ui-server")
    child = parent.bind(stage="map", tenant_id="t-uuid", trace_id="tr-uuid")
    assert parent.extra is not None and child.extra is not None
    assert "stage" not in parent.extra
    assert child.extra["service"] == "dis-ui-server"
    assert child.extra["stage"] == "map"
    assert child.extra["tenant_id"] == "t-uuid"


def test_context_fields_appear_in_json_record() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter("%(message)s"))
    base = logging.getLogger("test.dis.logging")
    base.handlers = [handler]
    base.setLevel(logging.INFO)
    base.propagate = False

    log = DisLoggerAdapter(base, {"service": "csv-ingest-worker", "stage": "preflight"})
    log.info("chunk received", extra={"trace_id": "tr-123"})

    payload = json.loads(stream.getvalue())
    assert payload["service"] == "csv-ingest-worker"
    assert payload["stage"] == "preflight"
    assert payload["trace_id"] == "tr-123"
    assert payload["message"] == "chunk received"


@pytest.fixture
def _restore_root_logger() -> Any:
    """``configure_logging`` replaces the root handlers; put them back afterwards."""
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    yield
    root.handlers = original_handlers
    root.setLevel(original_level)


def _last_root_record(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    """Parse the last line the root StreamHandler wrote (it defaults to stderr)."""
    payload: dict[str, Any] = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    return payload


def test_configure_logging_emits_severity_not_levelname(
    capsys: pytest.CaptureFixture[str], _restore_root_logger: Any
) -> None:
    """LOAD-BEARING: Cloud Logging reads ``severity``.

    An entry keyed ``levelname`` lands at DEFAULT, so no log-based alert and no
    ``severity>=ERROR`` query matches it — a broken service reads as healthy.
    """
    configure_logging(logging.INFO)
    get_logger("streaming-consumer").error("poll pass failed; retrying")

    payload = _last_root_record(capsys)
    assert payload["severity"] == "ERROR"
    assert "levelname" not in payload
    # The context binding and the message text are untouched by the rename.
    assert payload["service"] == "streaming-consumer"
    assert payload["message"] == "poll pass failed; retrying"


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
def test_every_level_name_is_a_cloud_logging_severity(
    level: str, capsys: pytest.CaptureFixture[str], _restore_root_logger: Any
) -> None:
    """The rename carries the VALUE through unmapped, which is only safe because
    all five Python level names are members of Cloud Logging's LogSeverity
    vocabulary. A custom level added via ``logging.addLevelName`` would break
    that correspondence and fail here.
    """
    configure_logging(logging.DEBUG)
    get_logger("dis-ui-server").log(getattr(logging, level), "probe")

    assert _last_root_record(capsys)["severity"] == level
