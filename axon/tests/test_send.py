"""The send path: what it records, what it never raises, and the hole it cannot close.

FAKES RATHER THAN A REAL PROVIDER AND A REAL DATABASE, which is the seam CM's EmailSender
Protocol established and the reason its suite never reaches SendGrid. The fakes here satisfy the
same Protocol the real adapter does, asserted below so a Protocol change cannot leave them
passing against a contract nothing implements.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import pytest
from axon import (
    Channel,
    ChannelAdapter,
    ChannelSendError,
    DeliveryRecord,
    DeliveryState,
    LedgerWriteError,
    Message,
    SendOutcome,
    send_platform,
)
from axon import send as send_module


class _FakeAdapter:
    """An adapter that accepts, or raises whatever it was given."""

    def __init__(self, *, fail_with: ChannelSendError | None = None) -> None:
        self._fail_with = fail_with
        self.sent: list[Message] = []

    @property
    def channel(self) -> Channel:
        return Channel.EMAIL

    @property
    def provider(self) -> str:
        return "fake"

    async def send(self, message: Message) -> None:
        if self._fail_with is not None:
            raise self._fail_with
        self.sent.append(message)


@dataclass
class _Recorded:
    """What the fake ledger was asked to write."""

    records: list[DeliveryRecord]


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> _Recorded:
    """Capture the ledger write at the MODULE send.py calls it through.

    Patched here rather than at axon.ledger, because a test that patched the other name would
    pass against a send path that had stopped calling it. Same trap the Synapse suites name.
    """
    captured = _Recorded(records=[])

    async def fake_record(engine: object, record: DeliveryRecord) -> None:
        captured.records.append(record)

    monkeypatch.setattr(send_module, "record_platform_delivery", fake_record)
    return captured


def _message() -> Message:
    return Message(
        channel=Channel.EMAIL,
        recipient="oncall@sevyn8.example",
        subject="a subject",
        body="a body",
    )


async def _send(adapter: Any, **overrides: Any) -> SendOutcome:
    kwargs: dict[str, Any] = {
        "engine": object(),
        "adapter": adapter,
        "message": _message(),
        "notification_class": "test.event",
        "subject_kind": "test",
        "subject_id": "abc",
    }
    kwargs.update(overrides)
    return await send_platform(**kwargs)


def test_the_fake_adapter_satisfies_the_port() -> None:
    """THE VACUITY GUARD FOR EVERY TEST BELOW. A fake that had drifted from the Protocol would
    make all of them pass against a contract the real adapter does not share."""
    assert isinstance(_FakeAdapter(), ChannelAdapter)


async def test_an_accepted_send_records_accepted(recorded: _Recorded) -> None:
    """THE HAPPY PATH, and the baseline every failure test below needs."""
    adapter = _FakeAdapter()

    outcome = await _send(adapter)

    assert outcome.state is DeliveryState.ACCEPTED
    assert outcome.recorded is True
    assert len(adapter.sent) == 1
    assert len(recorded.records) == 1
    row = recorded.records[0]
    assert row.state is DeliveryState.ACCEPTED
    assert row.failure_detail is None
    assert row.recipient == "oncall@sevyn8.example"


async def test_a_provider_failure_is_recorded_and_never_raised(recorded: _Recorded) -> None:
    """THE ONE THAT MATTERS MOST, AND IT IS THE COUPLING RULE.

    The producer has already committed by the time this runs: an operator enabled a monitor and
    the row is in the database. A provider refusal must not travel back and fail that request.

    AND IT MUST NOT VANISH EITHER. Fire-and-record is not fire-and-forget: the row is written
    with state='failed' and the detail, so the failure is countable afterwards. A swallowed
    failure that left nothing behind would be indistinguishable from nobody having tried.
    """
    adapter = _FakeAdapter(fail_with=ChannelSendError("provider said 403", provider="fake", status_code=403))

    outcome = await _send(adapter)

    assert outcome.state is DeliveryState.FAILED
    assert outcome.recorded is True
    assert len(recorded.records) == 1
    assert recorded.records[0].state is DeliveryState.FAILED
    assert recorded.records[0].failure_detail == "provider said 403"


async def test_a_ledger_failure_returns_unrecorded_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE HOLE THIS SLICE CANNOT CLOSE, PINNED SO IT IS NOT MISTAKEN FOR A BUG.

    If the ledger write fails there is no row, there may have been an email, and the producer
    succeeded. Nothing afterwards can tell that anything was owed, because the row that failed to
    be written was the only evidence of the intent.

    It still does not raise: failing the enable would trade a lost record for a lost enablement.
    It comes back with recorded=False so the caller can log at ERROR, which is the most this
    slice can do and is exactly why send.py names this as the reason the queue exists.
    """

    async def boom(engine: object, record: DeliveryRecord) -> None:
        raise LedgerWriteError("the ledger is unreachable")

    monkeypatch.setattr(send_module, "record_platform_delivery", boom)

    outcome = await _send(_FakeAdapter())

    assert outcome.state is DeliveryState.ACCEPTED
    assert outcome.recorded is False


async def test_the_delivery_id_is_a_uuid7_minted_before_the_send(recorded: _Recorded) -> None:
    """MINTED BY THE CALLER, WHICH IS WHAT LETS THE GRANT HOLD NO SELECT.

    A server-side DEFAULT would need RETURNING to learn the id, RETURNING needs SELECT, and
    axon_sender deliberately has none. Version 7 rather than 4 because uuid4 is banned
    project-wide and because the id then carries the instant.
    """
    await _send(_FakeAdapter())

    delivery_id = recorded.records[0].delivery_id
    assert isinstance(delivery_id, UUID)
    assert delivery_id.version == 7


async def test_two_sends_are_two_rows(recorded: _Recorded) -> None:
    """NO IDEMPOTENCY, DELIBERATELY, AND THIS PINS THE DECISION.

    Two producer events are two deliveries and two rows. There is nothing to deduplicate against
    in this slice: the call is in-process and synchronous, once per event.

    THE QUEUE CHANGES THIS and the obvious mechanism will fail: ON CONFLICT has to read the
    arbiter index and this role holds no SELECT, which is exactly how slice 5e lost two days.
    ledger.py's docstring records the two mechanisms that do work. If this test is failing
    because somebody added deduplication, they should have added a grant too.
    """
    adapter = _FakeAdapter()

    await _send(adapter)
    await _send(adapter)

    assert len(recorded.records) == 2
    assert recorded.records[0].delivery_id != recorded.records[1].delivery_id
