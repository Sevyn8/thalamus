"""The three-tier swallow on the csv.received pull loop (L6, second instance).

This service carried its own copy of the loop, so the first L6 fix (which landed
on streaming_consumer/clients/pubsub.py) did not reach it. It surfaced in
production only once `severity` was mapped for Cloud Logging: a severity>=ERROR
query then showed this worker logging the storm every ~11 seconds.

The loop still survives everything (a dead worker is worse than a noisy one), so
no tier re-raises. What changed is which tier each error lands in:

Tier 1  DeadlineExceeded -> DEBUG, no traceback. An EMPTY subscription is the
        normal steady state: the synchronous pull holds the connection open until
        the 10s client deadline and then raises. The old single bare catch logged
        that at ERROR with a full traceback every ~11s, roughly 7,800 entries per
        instance per day, which buried a successful run in a log read.
Tier 2  transient transport/DB -> WARNING, message text unchanged.
Tier 3  anything else -> ERROR + traceback + ``bug=True``.

These are unit tests with a faked poll_once. They cannot be emulator integration
tests: the Pub/Sub emulator returns an empty PullResponse just UNDER the client
deadline (measured on this identical synchronous call — same SubscriberClient.pull,
same timeout=10: 1.06s at timeout=2, 4.05s at timeout=5, 9.12s at timeout=10), so
it never raises DeadlineExceeded at all. The storm is real-Pub/Sub-only.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from google.api_core.exceptions import DeadlineExceeded, PermissionDenied, ServiceUnavailable
from google.cloud import pubsub_v1
from sqlalchemy.exc import OperationalError

from csv_ingest_worker.config import SERVICE_NAME
from csv_ingest_worker.subscriber import Subscriber

# api_core exception constructors are untyped; the ignore lands once, here.
_DEADLINE = DeadlineExceeded("Deadline Exceeded")  # type: ignore[no-untyped-call]
_UNAVAILABLE = ServiceUnavailable("backend unavailable")  # type: ignore[no-untyped-call]
_FORBIDDEN = PermissionDenied("caller lacks consume")  # type: ignore[no-untyped-call]
_DB_BLIP = OperationalError("SELECT 1", {}, Exception("server closed the connection"))


class _StubSubscriberClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def subscription_path(self, project: str, name: str) -> str:
        return f"projects/{project}/subscriptions/{name}"

    def get_subscription(self, request: dict[str, Any]) -> None:
        return None  # exists; the startup existence check passes


def _subscriber(monkeypatch: pytest.MonkeyPatch, *, raises: BaseException) -> Subscriber:
    """A subscriber whose FIRST poll raises ``raises`` and whose second cancels out.

    CancelledError derives from BaseException, so it escapes every ``except
    Exception`` tier and ends the otherwise-infinite loop after exactly one
    handled pass.
    """
    monkeypatch.setenv("PUBSUB_EMULATOR_HOST", "127.0.0.1:9")
    monkeypatch.setattr(pubsub_v1, "SubscriberClient", _StubSubscriberClient)

    async def _no_sleep(_seconds: float) -> None:
        return None

    # Process-global for the duration of the test (monkeypatch restores it); the
    # loop's only await between passes is asyncio.sleep(1) and there is no seam.
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    subscriber = Subscriber(project_id="local-dis", pipeline=object())  # type: ignore[arg-type]

    calls = {"n": 0}

    async def _poll(*args: Any, **kwargs: Any) -> int:
        calls["n"] += 1
        if calls["n"] == 1:
            raise raises
        raise asyncio.CancelledError

    monkeypatch.setattr(subscriber, "poll_once", _poll)
    return subscriber


async def _run_one_pass(subscriber: Subscriber) -> None:
    with pytest.raises(asyncio.CancelledError):
        await subscriber.run_forever()


async def test_empty_subscription_deadline_is_debug_not_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """LOAD-BEARING: the 7,800-entries-a-day storm.

    An empty-queue pass is NORMAL. If this regresses to ERROR (or to a traceback),
    the loop resumes burying real output in a log read.
    """
    subscriber = _subscriber(monkeypatch, raises=_DEADLINE)
    caplog.set_level("DEBUG")

    await _run_one_pass(subscriber)

    records = [r for r in caplog.records if r.name == SERVICE_NAME]
    empty = [r for r in records if r.getMessage() == "empty pull; no messages this pass"]
    assert [r.levelname for r in empty] == ["DEBUG"]
    assert not any(r.levelname in {"WARNING", "ERROR"} for r in records)
    assert all(r.exc_info is None for r in records)


@pytest.mark.parametrize(
    "exc",
    [
        _UNAVAILABLE,
        _DB_BLIP,
    ],
    ids=["pubsub-503", "db-blip"],
)
async def test_transient_error_warns_with_unchanged_message(
    exc: BaseException, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    subscriber = _subscriber(monkeypatch, raises=exc)
    caplog.set_level("DEBUG")

    await _run_one_pass(subscriber)

    records = [r for r in caplog.records if "poll pass failed" in r.getMessage()]
    assert len(records) == 1
    assert records[0].levelname == "WARNING"
    # Byte-identical to the message that shipped before the tier split.
    assert records[0].getMessage() == "poll pass failed; retrying"


@pytest.mark.parametrize(
    "exc",
    [
        TypeError("process_message() missing 1 required positional argument"),
        _FORBIDDEN,
    ],
    ids=["programming", "config"],
)
async def test_non_transient_error_logs_bug_at_error(
    exc: BaseException, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """LOAD-BEARING: a TypeError in the pipeline, and a 403 on the subscription, must
    both surface. PermissionDenied is api_core ClientError (4xx), deliberately OUTSIDE
    the ServerError-based transient tuple - retrying a config error in silence forever
    is the failure mode this tier exists to prevent. This worker holds project-level
    pubsub.viewer for the startup existence check, so a revoked binding is exactly the
    403 that must not read as a transient blip."""
    subscriber = _subscriber(monkeypatch, raises=exc)
    caplog.set_level("DEBUG")

    await _run_one_pass(subscriber)

    records = [r for r in caplog.records if r.getMessage().startswith("BUG:")]
    assert len(records) == 1
    assert records[0].levelname == "ERROR"
    assert records[0].exc_info is not None
    assert getattr(records[0], "bug", None) is True


@pytest.mark.parametrize(
    "exc",
    [
        _DEADLINE,
        _UNAVAILABLE,
        TypeError("boom"),
    ],
    ids=["deadline", "transient", "programming"],
)
async def test_loop_survives_every_tier(
    exc: BaseException, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No tier re-raises: the loop reaches a second poll in every case."""
    subscriber = _subscriber(monkeypatch, raises=exc)
    await _run_one_pass(subscriber)
