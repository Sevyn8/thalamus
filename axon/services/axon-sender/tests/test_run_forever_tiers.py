"""run_forever's three exception tiers, asserted one at a time and then against each other.

WHAT THIS EXISTS FOR. The loop used to have ONE handler, which logged an empty queue and a
lost IAM binding with the same words at the same level. An idle subscription produces a pass
about every eleven seconds (timeout=10 then sleep(1)), so 86400 / 11 is about 7,854 identical
WARNING lines per instance per day, and a real failure arrived into that stream unread.

THE ORDERING IS THE PART MOST WORTH PINNING, and it is not obvious from reading the code.
DeadlineExceeded IS a subclass of ServerError, and ServerError is in the transient tuple. So if
the two clauses are ever reversed, or if DeadlineExceeded is folded into the tuple, every empty
pull silently becomes a WARNING again and the change is undone with nothing failing. Asserting
the quiet tier alone cannot catch that: the empty-pull test would still pass while a
PermissionDenied was being retried forever as a transient. The two are therefore asserted
together at the bottom of this file.

NO Subscriber IS CONSTRUCTED. Its __post_init__ builds a real pubsub_v1.SubscriberClient and
calls _require_subscription, so constructing one needs a network. run_forever touches exactly
two attributes, self.heartbeat and self.poll_once, so the real method is driven against a
stand-in carrying those. The code under test is the real run_forever, not a copy of its shape.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest
from axon_sender import subscriber as subscriber_module
from axon_sender.subscriber import Subscriber
from google.api_core.exceptions import (
    DeadlineExceeded,
    NotFound,
    PermissionDenied,
    ServerError,
    ServiceUnavailable,
    TooManyRequests,
)

_LOGGER_NAME = "axon-sender"


class _StopLoopError(Exception):
    """Raised from the patched sleep to end the otherwise infinite loop.

    Raised from asyncio.sleep, which every tier calls INSIDE its except block, so it propagates
    out of run_forever instead of being caught again by a later clause. That is what makes one
    pass observable.
    """


@pytest.fixture
def one_pass(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Drive exactly one pass of the real run_forever, raising `exc` from poll_once."""

    async def _sleep(_seconds: float) -> None:
        raise _StopLoopError

    # Patched on the asyncio module itself rather than through subscriber_module.asyncio: the
    # object is the same, and reaching through a module that declares __all__ is an mypy
    # attr-defined error rather than a real distinction.
    monkeypatch.setattr(asyncio, "sleep", _sleep)

    async def _run(exc: BaseException) -> None:
        async def _poll_once() -> int:
            raise exc

        stub = SimpleNamespace(
            heartbeat=SimpleNamespace(beat=lambda: None),
            poll_once=_poll_once,
            _sub_path="projects/p/subscriptions/s",
        )
        with pytest.raises(_StopLoopError):
            await Subscriber.run_forever(stub)  # type: ignore[arg-type]

    return _run


def _records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Only the loop's own records, dropping the one-off 'subscribed' line at INFO."""
    return [r for r in caplog.records if not r.getMessage().startswith("subscribed;")]


# ---------------------------------------------------------------------------
# Tier 1: an empty pull is a non-event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_empty_pull_logs_at_debug_and_never_at_warning(
    one_pass: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """THE DEFECT THIS CLOSES. An idle subscription raises DeadlineExceeded on every pass, and
    it used to arrive as a WARNING named axon.poll.failed about every eleven seconds."""
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
    await one_pass(DeadlineExceeded("Deadline Exceeded"))  # type: ignore[no-untyped-call]

    records = _records(caplog)
    assert records, "the empty-pull branch logged nothing at all; this test would prove nothing"
    assert [r.levelno for r in records] == [logging.DEBUG], (
        "an empty pull is the normal steady state and must not be logged above DEBUG"
    )
    assert "empty pull" in records[0].getMessage()

    for record in records:
        assert getattr(record, "event", None) != "axon.poll.failed", (
            "an empty queue is still being reported as a failure"
        )


# ---------------------------------------------------------------------------
# Tier 2: a real transport error stays loud
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(ServiceUnavailable("503"), id="service-unavailable"),  # type: ignore[no-untyped-call]
        pytest.param(TooManyRequests("429"), id="too-many-requests"),  # type: ignore[no-untyped-call]
        pytest.param(ConnectionRefusedError("socket"), id="oserror"),
    ],
)
@pytest.mark.asyncio
async def test_a_transient_transport_error_still_logs_at_warning(
    one_pass: Any, caplog: pytest.LogCaptureFixture, exc: BaseException
) -> None:
    """THE HALF THAT MUST NOT BE SILENCED. Quieting the empty pull is only correct if a real
    pull failure is still visible, so this asserts the level AND the event name survive.

    TooManyRequests and ConnectionRefusedError are here because neither is a ServerError:
    dropping either from the tuple would send a 429 or a refused socket to the BUG tier and
    report a quota blip as a programming error.
    """
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
    await one_pass(exc)

    records = _records(caplog)
    assert records, "the transient branch logged nothing"
    assert [r.levelno for r in records] == [logging.WARNING]
    assert getattr(records[0], "event", None) == "axon.poll.failed"
    assert getattr(records[0], "error_type", None) == type(exc).__name__, (
        "the error type is what tells a reader which failure this was"
    )
    assert records[0].exc_info is None, "a transient retry does not need a traceback"


# ---------------------------------------------------------------------------
# Tier 3: a configuration error is a bug, not a blip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(PermissionDenied("403"), id="permission-denied"),  # type: ignore[no-untyped-call]
        pytest.param(NotFound("404"), id="not-found"),  # type: ignore[no-untyped-call]
        pytest.param(TypeError("a real bug"), id="programming-error"),
    ],
)
@pytest.mark.asyncio
async def test_a_configuration_or_programming_error_reaches_the_bug_tier(
    one_pass: Any, caplog: pytest.LogCaptureFixture, exc: BaseException
) -> None:
    """THE CASE WORTH MORE THAN THE NOISE REDUCTION. A revision that has lost its IAM binding
    on the subscription raises PermissionDenied on every pass. Under the single handler this
    replaced it logged one WARNING line every eleven seconds, indistinguishable from an idle
    queue, and retried for ever while draining nothing.

    The traceback is asserted, not just the level: ERROR without one says a thing is broken and
    not where.
    """
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
    await one_pass(exc)

    records = _records(caplog)
    assert records, "the bug branch logged nothing"
    assert [r.levelno for r in records] == [logging.ERROR]
    assert records[0].exc_info is not None, "the BUG tier must carry a traceback"
    assert getattr(records[0], "bug", None) is True, "the bug marker is how this is queried"
    assert getattr(records[0], "event", None) != "axon.poll.failed", (
        "a configuration error is not the transient poll failure and must not share its name"
    )


# ---------------------------------------------------------------------------
# The ordering, asserted as one fact rather than two
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deadline_exceeded_and_permission_denied_are_told_apart(
    one_pass: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """THE ORDERING PROOF, AND THE REASON IT IS ONE TEST AND NOT TWO.

    DeadlineExceeded is a ServerError subclass and ServerError is in the transient tuple, so
    the clauses are only correct in one order. Two separate passing tests can coexist with a
    wrong order in ways that are easy to miss, so both outcomes are asserted here against the
    same run: the empty pull must be DEBUG and the permission failure must be ERROR, and if
    either clause moved they would collide on the same level.
    """
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
    await one_pass(DeadlineExceeded("Deadline Exceeded"))  # type: ignore[no-untyped-call]
    empty_levels = [r.levelno for r in _records(caplog)]

    caplog.clear()
    await one_pass(PermissionDenied("403"))  # type: ignore[no-untyped-call]
    denied_levels = [r.levelno for r in _records(caplog)]

    assert empty_levels == [logging.DEBUG], "an empty pull fell out of its own clause"
    assert denied_levels == [logging.ERROR], (
        "PermissionDenied was handled as something other than a bug. If it logged at WARNING "
        "it matched the transient tuple, which means a permanent config failure is being "
        "retried for ever at a level nobody reads."
    )
    assert empty_levels != denied_levels, (
        "the two ends of the split are being logged identically, which is the state this "
        "change existed to end"
    )


def test_deadline_exceeded_is_not_in_the_transient_tuple() -> None:
    """The same ordering fact, asserted against the tuple itself.

    Belt and braces on the test above: that one proves the behaviour, this one names the
    specific edit that would break it, so a reader who adds DeadlineExceeded to the tuple sees
    why rather than only that.
    """
    assert DeadlineExceeded not in subscriber_module._TRANSIENT_POLL_ERRORS, (
        "DeadlineExceeded has been added to the transient tuple. It is a ServerError subclass "
        "and must be caught by its own earlier clause, or every empty pull is a WARNING again."
    )
    assert issubclass(DeadlineExceeded, ServerError), (
        "DeadlineExceeded is no longer a ServerError subclass, so the ordering comment in "
        "subscriber.py is stale and the clause order may no longer matter"
    )
