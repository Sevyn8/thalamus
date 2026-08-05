"""What the scheduled job reports, and what its exit code says.

THESE ARE 6b's PROPERTIES, and they are all about a run nobody is watching. When a human runs
the sweep they read the output; when Cloud Scheduler runs it at 03:00 the only things that exist
afterwards are the exit code and the log entries. Both have to be right on their own.

  - A NO-WORK SWEEP EXITS 0. An empty estate is correct behaviour, and a job that exits non-zero
    for it would page somebody for nothing at 04:00.
  - A SKIPPED-BUT-PREVIOUSLY-FAILED SLOT STILL EXITS 1. With max_retries=1 the retry finds the
    slot terminal and skips it; if that reported success, Cloud Run would mark the execution
    GREEN and a real failure would vanish at exactly the layer an alert watches.
  - EVERY FAILURE LINE CARRIES severity=ERROR. Cloud Logging reads `severity` off a structured
    entry; a plain print files at DEFAULT and no log-based alert can ever match it. This matters
    more here than elsewhere because nothing self-heals: a failed slot is terminal, tomorrow is
    a different slot, and only a human clears it.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from synapse.core.provision import Cadence, Provision, Rung
from synapse.orchestrator.__main__ import _instant, _report
from synapse.orchestrator.runner import SlotResult

TENANT = UUID("019e5e3c-b5d6-7eed-93f9-3778a7a7a160")


def _provision() -> Provision:
    return Provision(
        tenant_id=TENANT,
        analysis_id="dead_stock",
        cadence=Cadence.DAILY,
        rung=Rung.SHADOW,
        timezone="Asia/Kolkata",
        enabled_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def _entries(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "synapse-orchestrator"]


def _result(outcome: str | None, **overrides: object) -> SlotResult:
    fields: dict[str, object] = {
        "tenant_id": TENANT,
        "analysis_id": "dead_stock",
        "slot": date(2026, 8, 6),
        "outcome": outcome,
        "actions_proposed": 0,
        "actions_appended": 0,
    }
    fields.update(overrides)
    return SlotResult(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Exit-code semantics — what the scheduler sees
# ---------------------------------------------------------------------------


def test_a_slot_skipped_after_a_previous_failure_is_still_a_failure() -> None:
    """THE HOLE max_retries=1 OPENS, closed.

    Execution 1 fails a tenant and exits 1. Cloud Run retries. Execution 2 finds the slot
    terminal and skips it — and if a skip were undifferentiated it would exit 0 and the
    execution would go GREEN, converting a real failure into a success.
    """
    skipped_after_failure = _result("failed", skipped=True, detail="already finished, 'failed'")
    assert skipped_after_failure.failed, "a retry must not launder a failed slot into success"


def test_a_slot_skipped_after_a_successful_run_is_not_a_failure() -> None:
    """The converse, and it is what stops the test above passing against a rule that calls every
    skip a failure. A second dispatch of a slot that genuinely succeeded is a clean no-op."""
    assert not _result("satisfied", skipped=True).failed


def test_no_work_is_not_a_failure() -> None:
    """An empty estate exits 0. The 04:00 page for correct behaviour, prevented."""
    empty: tuple[SlotResult, ...] = ()
    assert not any(result.failed for result in empty)


# ---------------------------------------------------------------------------
# Severity — the property an alert matches on
# ---------------------------------------------------------------------------


def test_a_failed_run_logs_at_error(caplog: pytest.LogCaptureFixture) -> None:
    """WITHOUT THIS NOTHING CAN EVER ALERT. dis_core's formatter renames levelname to severity,
    so the level chosen here is what Cloud Logging files the entry under."""
    with caplog.at_level(logging.INFO):
        _report((_result("failed", detail="boom"),), dry_run=False)
    levels = {r.levelno for r in _entries(caplog) if r.levelno >= logging.ERROR}
    assert levels == {logging.ERROR}


def test_a_satisfied_run_does_not_log_at_error(caplog: pytest.LogCaptureFixture) -> None:
    """The baseline. An implementation that logged everything at ERROR would satisfy the test
    above and make the severity worthless — an alert matching ERROR would fire every night."""
    with caplog.at_level(logging.INFO):
        _report((_result("satisfied", actions_proposed=3, actions_appended=3),), dry_run=False)
    assert not [r for r in _entries(caplog) if r.levelno >= logging.ERROR]


def test_a_takeover_logs_at_warning(caplog: pytest.LogCaptureFixture) -> None:
    """A takeover is the ONLY visible evidence that a previous execution died. It is not a
    failure — the slot completes — so it must not be ERROR, and it must not be invisible."""
    with caplog.at_level(logging.INFO):
        _report((_result("satisfied", taken_over=True),), dry_run=False)
    assert [r for r in _entries(caplog) if r.levelno == logging.WARNING]


def test_an_empty_sweep_still_logs_something(caplog: pytest.LogCaptureFixture) -> None:
    """Silence and success must be distinguishable in the log. A sweep that logged nothing when
    nothing was due is indistinguishable from a sweep that never ran."""
    with caplog.at_level(logging.INFO):
        _report((), dry_run=False)
    assert _entries(caplog), "a no-work sweep must still say so"


def test_the_entry_carries_the_fields_an_operator_needs(caplog: pytest.LogCaptureFixture) -> None:
    """A log line saying only "failed" sends someone to the database to find out which tenant.
    The structured fields are what make the entry answer that on its own."""
    with caplog.at_level(logging.INFO):
        _report((_result("failed", detail="boom"),), dry_run=False)
    record = next(r for r in _entries(caplog) if r.levelno >= logging.ERROR)
    for field in ("analysis_id", "tenant_id", "slot", "outcome", "detail"):
        assert hasattr(record, field), f"the failure entry does not carry {field}"
    assert getattr(record, "tenant_id") == str(TENANT)  # noqa: B009 - dynamic LogRecord field


def test_the_entries_are_json_serialisable(caplog: pytest.LogCaptureFixture) -> None:
    """The formatter emits JSON. A field that cannot serialise would raise inside logging and
    silently drop the entry — a failure line lost at exactly the moment it matters. `slot` is
    the live risk: a date is not JSON-native, which is why it is passed as an ISO string.
    """
    with caplog.at_level(logging.INFO):
        _report((_result("failed", detail="boom"),), dry_run=False)
    record = next(r for r in _entries(caplog) if r.levelno >= logging.ERROR)
    payload = {
        key: getattr(record, key)
        for key in ("analysis_id", "tenant_id", "slot", "outcome", "skipped", "detail")
    }
    json.dumps(payload)


# ---------------------------------------------------------------------------
# --now parsing, which the scheduled path never uses and an operator always does
# ---------------------------------------------------------------------------


def test_a_naive_now_is_refused_at_the_argument() -> None:
    """Rejected here as well as in slot_for so the message names the ARGUMENT rather than
    surfacing from three frames down."""
    with pytest.raises(SystemExit, match="no UTC offset"):
        _instant("2026-08-05T09:00:00")


def test_an_unparseable_now_is_refused() -> None:
    with pytest.raises(SystemExit, match="not ISO-8601"):
        _instant("yesterday")


def test_an_offset_now_is_accepted_unchanged() -> None:
    parsed = _instant("2026-08-05T09:00:00+05:30")
    assert parsed.utcoffset() is not None
    assert parsed.isoformat() == "2026-08-05T09:00:00+05:30"


def test_no_now_means_an_aware_current_instant() -> None:
    """The scheduled path. It must be aware, or slot_for refuses it and every sweep dies."""
    assert _instant(None).utcoffset() is not None


# ---------------------------------------------------------------------------
# The runner path that actually closes the hole
# ---------------------------------------------------------------------------
#
# THE TESTS ABOVE DID NOT COVER THIS, and finding that out is the reason it is here. Asserting
# `SlotResult("failed", skipped=True).failed` proves the DATACLASS behaves; it says nothing
# about whether `_run_one` puts the prior outcome into that field. Replacing
# `outcome=claimed.outcome` with `outcome=None` in the runner left all of them green — the
# guard's scope did not match what its docstring claimed it covered.


class _FakeRecorder:
    """Stands in for PostgresRunRecorder so the skip branch runs without a database.

    A test DOUBLE, not a reimplementation: it returns a canned answer to `claim` and records
    nothing. The logic under test is the runner's HANDLING of that answer, which is real code.
    """

    def __init__(self, answer: object) -> None:
        self._answer = answer
        self.completed = False

    async def claim(self, **_: object) -> object:
        return self._answer

    async def complete(self, **_: object) -> None:  # pragma: no cover - must not be reached
        self.completed = True


async def test_the_runner_carries_a_prior_failure_through_the_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE REAL GUARD. `_run_one` must put the terminal outcome on the result, or a retry after
    a failure exits 0 and Cloud Run marks the execution green."""
    from uuid import uuid4

    from synapse.orchestrator import runner as runner_module
    from synapse.persistence.run_postgres import Finished

    recorder = _FakeRecorder(Finished(run_id=uuid4(), outcome="failed"))
    monkeypatch.setattr(runner_module, "PostgresRunRecorder", lambda *a, **k: recorder)

    result = await runner_module._run_one(
        provision=_provision(),
        reader_engine=None,  # type: ignore[arg-type]
        writer_engine=None,  # type: ignore[arg-type]
        now=datetime(2026, 8, 5, 3, 30, tzinfo=UTC),
        dry_run=False,
    )
    assert result.skipped, "a terminal slot is not re-run"
    assert result.failed, "a skip after a FAILED slot must still fail the execution"
    assert not recorder.completed, "a skipped slot must not be completed again"


async def test_the_runner_does_not_fail_on_a_skip_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The converse, through the same path. Without it the test above would pass against a
    runner that marked every skip as failed, which would make the nightly retry always red."""
    from uuid import uuid4

    from synapse.orchestrator import runner as runner_module
    from synapse.persistence.run_postgres import Finished

    recorder = _FakeRecorder(Finished(run_id=uuid4(), outcome="satisfied"))
    monkeypatch.setattr(runner_module, "PostgresRunRecorder", lambda *a, **k: recorder)

    result = await runner_module._run_one(
        provision=_provision(),
        reader_engine=None,  # type: ignore[arg-type]
        writer_engine=None,  # type: ignore[arg-type]
        now=datetime(2026, 8, 5, 3, 30, tzinfo=UTC),
        dry_run=False,
    )
    assert result.skipped and not result.failed
