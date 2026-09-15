"""Config resolution: required values raise, never default (code-quality rule 4)."""

from __future__ import annotations

import importlib

import pytest

import dis_ui_server.config as config_module
from dis_core.errors import DisError
from dis_ui_server.config import (
    API_PREFIX,
    CSV_RECEIVED_TOPIC,
    CSV_UPLOAD_BODY_CEILING_BYTES,
    CSV_UPLOAD_MAX_FILE_BYTES,
    SERVICE_NAME,
    UiServerConfig,
)


def _set_all_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_URL", "postgresql+psycopg://u:p@localhost:5433/ithina_dis_db")
    # DIS_AUTH_MODE is DECLARED because this module builds its own environment rather than
    # going through conftest's set_unit_env. The default is AUTH0, which requires an issuer
    # and an audience; these tests want the HS256 stub, and the URL above is loopback, which
    # is what the stub guard requires.
    monkeypatch.setenv("DIS_AUTH_MODE", "STUB")
    # STUB also requires the explicit local/test declaration (P1-SEC-001); this module builds
    # its own environment, so it declares it here the way conftest's unit env does.
    monkeypatch.setenv("DIS_ALLOW_STUB_AUTH", "1")
    monkeypatch.setenv("GCS_BUCKET_BRONZE", "ithina-bronze-raw")
    monkeypatch.setenv("PUBSUB_PROJECT_ID", "local-dis")


@pytest.mark.parametrize("missing", ["POSTGRES_URL", "GCS_BUCKET_BRONZE", "PUBSUB_PROJECT_ID"])
def test_missing_required_env_raises(missing: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # Fail-fast at startup is the crashloop signal for MISCONFIGURATION — kept
    # strictly separate from the present-but-unreachable case (test_health.py),
    # which must NOT crash startup.
    _set_all_required(monkeypatch)
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(DisError, match=missing):
        UiServerConfig.from_env()


def test_present_required_env_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_all_required(monkeypatch)
    config = UiServerConfig.from_env()
    assert config.postgres_url.endswith("/ithina_dis_db")
    assert config.gcs_bucket_bronze == "ithina-bronze-raw"
    assert config.pubsub_project_id == "local-dis"


def test_service_constants_frozen() -> None:
    assert SERVICE_NAME == "dis-ui-server"
    assert API_PREFIX == "/api/v1"
    # The publish target defaults to the contract topic name; the upload ceiling
    # is a frozen constant with body headroom above the file cap.
    assert CSV_RECEIVED_TOPIC == "csv.received"
    assert CSV_UPLOAD_MAX_FILE_BYTES == 10 * 1024 * 1024
    assert CSV_UPLOAD_BODY_CEILING_BYTES > CSV_UPLOAD_MAX_FILE_BYTES


def test_csv_received_topic_defaults_to_contract_name(monkeypatch: pytest.MonkeyPatch) -> None:
    # No override -> the contract literal, so local dev is byte-for-byte unchanged.
    monkeypatch.delenv("CSV_RECEIVED_TOPIC", raising=False)
    reloaded = importlib.reload(config_module)
    assert reloaded.CSV_RECEIVED_TOPIC == "csv.received"


def test_csv_received_topic_honours_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    # Deployment (terraform, from the pubsub module output) points the publish at the
    # actually-provisioned short name; the constant resolves at import, hence reload.
    monkeypatch.setenv("CSV_RECEIVED_TOPIC", "dis-csv-received")
    try:
        reloaded = importlib.reload(config_module)
        assert reloaded.CSV_RECEIVED_TOPIC == "dis-csv-received"
    finally:
        monkeypatch.delenv("CSV_RECEIVED_TOPIC", raising=False)
        importlib.reload(config_module)


# -- Gemini operational knobs (GEMINI_MODEL / _TIMEOUT_S / _THINKING_BUDGET) ---------


def _clear_new_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GEMINI_MODEL", "GEMINI_TIMEOUT_S", "GEMINI_THINKING_BUDGET"):
        monkeypatch.delenv(name, raising=False)


def test_new_gemini_knobs_unset_resolve_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # Unset -> None so the suggester applies its own built-in default (criterion 2 evidence
    # is asserted on the suggester in test_mapping_suggestions.py; here we prove config is None).
    _set_all_required(monkeypatch)
    _clear_new_gemini(monkeypatch)
    config = UiServerConfig.from_env()
    assert config.gemini_model is None
    assert config.gemini_timeout_s is None
    assert config.gemini_thinking_budget is None


def test_new_gemini_knobs_valid_values_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_all_required(monkeypatch)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("GEMINI_TIMEOUT_S", "12.5")
    monkeypatch.setenv("GEMINI_THINKING_BUDGET", "128")
    config = UiServerConfig.from_env()
    assert config.gemini_model == "gemini-2.5-pro"
    assert config.gemini_timeout_s == 12.5
    assert config.gemini_thinking_budget == 128


@pytest.mark.parametrize(
    ("value", "expected"),
    [("-1", -1), ("0", 0), ("512", 512)],  # -1=automatic and 0=disabled must PASS (the boundary)
)
def test_thinking_budget_boundary_values_pass(
    value: str, expected: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Item F: the guard rejects < -1 but MUST accept -1 (automatic) and 0 (disabled). The
    # raise-test covers -2; this pins the accepted side of the boundary so the guard can't
    # be tightened past -1/0 without a failing test.
    _set_all_required(monkeypatch)
    _clear_new_gemini(monkeypatch)
    monkeypatch.setenv("GEMINI_THINKING_BUDGET", value)
    assert UiServerConfig.from_env().gemini_thinking_budget == expected


@pytest.mark.parametrize("value", ["0.001", "20", "600"])  # smallest-ish and normal positives
def test_timeout_positive_values_pass(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # Item F complement: any value > 0 is accepted; only <= 0 raises (tested separately).
    _set_all_required(monkeypatch)
    _clear_new_gemini(monkeypatch)
    monkeypatch.setenv("GEMINI_TIMEOUT_S", value)
    assert UiServerConfig.from_env().gemini_timeout_s == float(value)


@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("GEMINI_MODEL", ""),
        ("GEMINI_MODEL", "   "),
        ("GEMINI_TIMEOUT_S", ""),
        ("GEMINI_TIMEOUT_S", "abc"),
        ("GEMINI_TIMEOUT_S", "0"),
        ("GEMINI_TIMEOUT_S", "-3"),
        ("GEMINI_THINKING_BUDGET", ""),
        ("GEMINI_THINKING_BUDGET", "x"),
        ("GEMINI_THINKING_BUDGET", "1.5"),
        ("GEMINI_THINKING_BUDGET", "-2"),
    ],
)
def test_new_gemini_knobs_bad_values_raise_naming_the_var(
    var: str, value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Set-but-empty / unparseable / out-of-domain -> loud DisError naming the variable
    # (criterion 3); the three new knobs fail fast, unlike the silent GEMINI_VERTEX_* reads.
    _set_all_required(monkeypatch)
    _clear_new_gemini(monkeypatch)
    monkeypatch.setenv(var, value)
    with pytest.raises(DisError, match=var):
        UiServerConfig.from_env()
