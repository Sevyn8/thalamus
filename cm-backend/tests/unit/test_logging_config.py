"""Unit tests for the stdout JSON logging configuration.

The load-bearing assertion is the emitted level KEY. Cloud Logging reads
`severity` off a structured entry; any other key (`levelname`, `level`) leaves
every entry at DEFAULT, which silently breaks log-based alerting and every
`severity>=ERROR` query. These tests pin the key and the value vocabulary.
"""

import json
import logging

import pytest

from admin_backend.logging_config import configure_logging


@pytest.fixture
def restore_root_logger():
    """configure_logging replaces the root handlers; put them back afterwards."""
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    yield
    root.handlers = original_handlers
    root.setLevel(original_level)


def test_lg1_configure_logging_emits_severity_not_levelname(
    capsys, restore_root_logger
) -> None:
    configure_logging("INFO")
    logging.getLogger("test.admin_backend.logging").info("hello")

    payload = json.loads(capsys.readouterr().out.strip().split("\n")[-1])
    assert payload["severity"] == "INFO"
    assert "levelname" not in payload
    assert "level" not in payload
    # The other rename is unchanged.
    assert "timestamp" in payload
    assert "asctime" not in payload


@pytest.mark.parametrize(
    "level",
    ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
)
def test_lg2_every_level_value_is_a_cloud_logging_severity(
    level: str, capsys, restore_root_logger
) -> None:
    """LOAD-BEARING: the rename carries the VALUE through unmapped.

    All five Python level names are members of Cloud Logging's LogSeverity
    vocabulary, which is why no value mapping is needed. If a custom level were
    ever added via logging.addLevelName, this test would catch the mismatch.
    """
    configure_logging("DEBUG")
    logging.getLogger("test.admin_backend.logging").log(
        getattr(logging, level), "hello"
    )

    payload = json.loads(capsys.readouterr().out.strip().split("\n")[-1])
    assert payload["severity"] == level
