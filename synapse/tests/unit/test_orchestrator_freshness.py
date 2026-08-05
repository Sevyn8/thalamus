"""The freshness signal, and the contract the alert policy reads off it.

WHAT MAKES THESE DIFFERENT FROM THE OTHER ORCHESTRATOR TESTS. Everything else here asserts on
behaviour. Several of these assert on a WIRE FORMAT — the exact JSON field names a Cloud Monitoring
log-based metric extracts — because that pair is invisible to every compiler and every other test
in this suite. A rename of ``sale_age_days`` would pass mypy, pass ruff, pass the whole suite, and
silently leave the alert with no data while looking configured. This file is the join.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest

from synapse.orchestrator.freshness import (
    STALE_AFTER_DAYS,
    TenantFreshness,
    emit_tenant_freshness,
)

_TENANT = UUID("019fb16b-e402-7dce-b026-6fa9f4919242")
_NOW = datetime(2026, 8, 5, 3, 0, tzinfo=UTC)


def _fresh(age: int, *, ever_sold: bool = True) -> TenantFreshness:
    return TenantFreshness(
        tenant_id=_TENANT,
        latest_sale=date(2026, 8, 5) if ever_sold else None,
        age_days=age,
        ever_sold=ever_sold,
    )


# ---------------------------------------------------------------------------
# The threshold
# ---------------------------------------------------------------------------


def test_a_fresh_tenant_is_not_stale() -> None:
    """THE BASELINE, and it is not ceremony. Without it every staleness assertion below would also
    pass against a property that returned True unconditionally — the "a refusal test passes when
    everything is broken" failure this project has already paid for."""
    assert not _fresh(0).stale
    assert not _fresh(STALE_AFTER_DAYS).stale


def test_one_day_past_the_threshold_is_stale() -> None:
    assert _fresh(STALE_AFTER_DAYS + 1).stale


def test_the_boundary_is_inclusive_of_fresh() -> None:
    """Exactly at the threshold is FRESH; the alert compares GT, not GTE. Stated as a test because
    an off-by-one here means the alert fires a day early on every healthy tenant, which is the
    fastest possible route to it being ignored."""
    assert not _fresh(STALE_AFTER_DAYS).stale
    assert _fresh(STALE_AFTER_DAYS + 1).stale


def test_the_body_shop_at_seventeen_days_is_stale() -> None:
    """The live case, pinned. This is the tenant the alert fires on from creation (outstanding
    item 6) and the number is real, not illustrative: latest sale 2026-07-19."""
    age = (date(2026, 8, 5) - date(2026, 7, 19)).days
    assert age == 17
    assert _fresh(age).stale


# ---------------------------------------------------------------------------
# Never sold — a different problem from having stopped
# ---------------------------------------------------------------------------


def test_a_tenant_that_never_sold_still_produces_a_number() -> None:
    """A NULL age would emit no metric point, so the threshold could never fire for exactly the
    tenant that has never worked. The age is time since provisioning instead — honest, and
    thresholdable by the same policy."""
    entry = _fresh(40, ever_sold=False)
    assert entry.latest_sale is None
    assert entry.age_days == 40
    assert entry.stale


def test_ever_sold_distinguishes_stopped_from_never_started() -> None:
    """Same age, different problem, and the alert text branches on it."""
    assert _fresh(40, ever_sold=True).ever_sold is True
    assert _fresh(40, ever_sold=False).ever_sold is False


# ---------------------------------------------------------------------------
# THE WIRE FORMAT the log-based metric reads
# ---------------------------------------------------------------------------


def test_the_emitted_entry_carries_sale_age_days_at_the_top_level(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """THE CONTRACT WITH THE ALERT POLICY.

    ``modules/monitoring-alerts`` extracts ``EXTRACT(jsonPayload.sale_age_days)``. dis_core.logging
    flattens ``extra`` to the top level of the JSON payload, so the field must be a direct
    attribute of the record — verified here by reading the record rather than the formatted string,
    which is the same thing the formatter serialises.

    A NESTED PATH WOULD EXTRACT NOTHING, FOR EVER, while the metric looked correctly configured.
    """
    with caplog.at_level(logging.INFO, logger="synapse.orchestrator.freshness"):
        emit_tenant_freshness([_fresh(1)])

    (record,) = caplog.records
    for field in ("sale_age_days", "tenant_id", "latest_sale", "ever_sold", "stale"):
        assert hasattr(record, field), f"{field} is not on the record; the metric cannot extract it"
    assert record.sale_age_days == 1  # type: ignore[attr-defined]
    assert record.tenant_id == str(_TENANT)  # type: ignore[attr-defined]


def test_a_healthy_tenant_still_emits(caplog: pytest.LogCaptureFixture) -> None:
    """THE REASON THE METRIC IS THRESHOLDABLE AT ALL.

    An absence signal that is itself absent when things are healthy cannot be compared against
    anything: there would be no way to tell "fresh" from "the emitter stopped". So a fresh tenant
    emits the same field, at INFO, and the metric captures both severities.
    """
    with caplog.at_level(logging.INFO, logger="synapse.orchestrator.freshness"):
        emit_tenant_freshness([_fresh(0)])
    (record,) = caplog.records
    assert record.levelno == logging.INFO
    assert record.sale_age_days == 0  # type: ignore[attr-defined]


def test_a_stale_tenant_emits_at_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Severity is the human signal. The alert deliberately does NOT match on it — it matches the
    NUMBER — so that the policy fires on the measurement rather than on the log line's opinion."""
    with caplog.at_level(logging.INFO, logger="synapse.orchestrator.freshness"):
        emit_tenant_freshness([_fresh(STALE_AFTER_DAYS + 1)])
    (record,) = caplog.records
    assert record.levelno == logging.WARNING
    assert record.stale is True  # type: ignore[attr-defined]


def test_every_tenant_emits_exactly_one_entry(caplog: pytest.LogCaptureFixture) -> None:
    """PER TENANT, NOT PER PAIR. A tenant with both analyses provisioned must not emit twice, or
    every count built on this metric doubles for it."""
    other = UUID("019fb250-d099-7221-ab04-68f65fe68287")
    with caplog.at_level(logging.INFO, logger="synapse.orchestrator.freshness"):
        emit_tenant_freshness([_fresh(0), TenantFreshness(other, date(2026, 8, 1), 4, True)])
    assert len(caplog.records) == 2
    assert {r.tenant_id for r in caplog.records} == {str(_TENANT), str(other)}  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# The two sources of truth for one threshold
# ---------------------------------------------------------------------------


def test_the_terraform_threshold_matches_this_module() -> None:
    """TERRAFORM CANNOT READ A PYTHON CONSTANT, so ``stale_after_days`` is stated twice — once here
    and once where the module is instantiated. Two sources of truth for one number is exactly the
    duplication class this project keeps paying for, and the mitigation is that the disagreement is
    a TEST FAILURE rather than a discovery.

    If they drift, the alert and the log line disagree about the meaning of the word "stale": the
    emitter would mark a tenant healthy while the policy fired on it, or worse, the reverse.
    """
    staging = Path(__file__).resolve().parents[3] / "infra" / "envs" / "staging" / "main.tf"
    assert staging.is_file(), f"{staging} not found; update this path rather than deleting the test"

    body = staging.read_text(encoding="utf-8")
    block = re.search(r'module\s+"monitoring_alerts"\s*\{(.*?)\n\}', body, re.S)
    assert block, (
        'module "monitoring_alerts" is not instantiated in staging — '
        "an alerting module that is not wired watches nothing"
    )

    declared = re.search(r"stale_after_days\s*=\s*(\d+)", block.group(1))
    assert declared, (
        "stale_after_days is not set on the module; it would silently fall back to the variable default"
    )
    assert int(declared.group(1)) == STALE_AFTER_DAYS, (
        f"terraform says {declared.group(1)} days, freshness.py says {STALE_AFTER_DAYS}. "
        "One number, two places, and they must agree or 'stale' means two different things."
    )


def test_the_alert_policy_extracts_the_field_this_module_emits() -> None:
    """THE OTHER HALF OF THE SAME JOIN, and the direction that actually broke things this session:
    the module asserts a requirement on its counterpart and nobody checked the counterpart.

    Greps the terraform for the extractor path and asserts the field name matches what
    ``emit_tenant_freshness`` puts on the record. A rename on either side fails here.
    """
    module = Path(__file__).resolve().parents[3] / "infra" / "modules" / "monitoring-alerts" / "main.tf"
    assert module.is_file(), f"{module} not found"
    body = module.read_text(encoding="utf-8")

    extracted = re.search(r"value_extractor\s*=\s*\"EXTRACT\(jsonPayload\.(\w+)\)\"", body)
    assert extracted, (
        "no value_extractor found; the freshness metric would count log lines instead of measuring age"
    )
    field = extracted.group(1)

    import logging as _logging

    records: list[_logging.LogRecord] = []

    class _Capture(_logging.Handler):
        def emit(self, record: _logging.LogRecord) -> None:
            records.append(record)

    logger = _logging.getLogger("synapse.orchestrator.freshness")
    handler = _Capture()
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(_logging.INFO)
    try:
        emit_tenant_freshness([_fresh(2)])
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)

    assert records, "nothing was emitted"
    assert hasattr(records[0], field), (
        f"terraform extracts jsonPayload.{field} and the emitted record has no such attribute. "
        "The metric would have no data while looking correctly configured."
    )
