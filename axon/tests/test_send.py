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

from dis_core.ids import new_uuid7


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

    async def fake_record(engine: object, record: DeliveryRecord) -> bool:
        captured.records.append(record)
        # True means the row was new. The duplicate branch has its own test below.
        return True

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
    """Drive the send path with a caller-minted delivery_id, as the consumer does.

    A FRESH UUIDv7 PER CALL unless a test pins one. Slice 2 moved the mint out of send_platform
    to the producer, so the id is now an argument; a test that reused one id across calls would
    be asserting the idempotency path by accident rather than on purpose.
    """
    kwargs: dict[str, Any] = {
        "engine": object(),
        "adapter": adapter,
        "message": _message(),
        "delivery_id": new_uuid7(),
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


async def test_the_supplied_delivery_id_reaches_the_ledger_unchanged(recorded: _Recorded) -> None:
    """SUPPLIED BY THE CALLER, WHICH IS WHAT MAKES THE WHOLE SLICE IDEMPOTENT.

    Slice 1 minted it here, which was right while the call was in-process and once per producer
    event. Under a queue that would mint a NEW id per redelivery, so the same intent would reach
    the ledger as N rows and pk_platform_deliveries would refuse none of them. The mint moved to
    the producer and rides in the envelope; this asserts the path does not substitute its own.

    A server-side DEFAULT is still not an option for the same reason as before: it would need
    RETURNING to learn the id, RETURNING needs SELECT, and axon_sender deliberately has none.
    """
    pinned = new_uuid7()

    await _send(_FakeAdapter(), delivery_id=pinned)

    delivery_id = recorded.records[0].delivery_id
    assert isinstance(delivery_id, UUID)
    assert delivery_id == pinned
    assert delivery_id.version == 7


async def test_two_distinct_deliveries_are_two_rows(recorded: _Recorded) -> None:
    """TWO PRODUCER EVENTS ARE TWO DELIVERIES AND TWO ROWS, which is unchanged by the queue.

    Idempotency is keyed on delivery_id, so it deduplicates a REDELIVERY of one message and not
    two genuine sends. If this ever collapses to one row, the mechanism has started deduplicating
    on something the producer did not intend as a key.
    """
    adapter = _FakeAdapter()

    await _send(adapter)
    await _send(adapter)

    assert len(recorded.records) == 2
    assert recorded.records[0].delivery_id != recorded.records[1].delivery_id


async def test_a_redelivery_of_one_message_is_reported_as_a_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE IDEMPOTENCY PATH, FROM THE SEND SIDE.

    record_platform_delivery returns False when pk_platform_deliveries already held this id, and
    the outcome carries that through as `duplicate` so the consumer can ack without writing a
    second row and can log that a redelivery happened.

    recorded IS TRUE AND duplicate IS TRUE AT THE SAME TIME, and both are needed: the evidence
    exists (so ack) and this pass did not create it (so say so). Collapsing them into one flag
    would make "the ledger is fine" and "I wrote it" the same statement, which they are not.
    """

    async def already_there(engine: object, record: DeliveryRecord) -> bool:
        return False

    monkeypatch.setattr(send_module, "record_platform_delivery", already_there)

    outcome = await _send(_FakeAdapter())

    assert outcome.recorded is True
    assert outcome.duplicate is True


async def test_a_first_write_is_not_reported_as_a_duplicate(recorded: _Recorded) -> None:
    """THE VACUITY GUARD FOR THE TEST ABOVE. A `duplicate` that were always True would make that
    assertion pass while the flag carried no information at all."""
    outcome = await _send(_FakeAdapter())

    assert outcome.recorded is True
    assert outcome.duplicate is False
