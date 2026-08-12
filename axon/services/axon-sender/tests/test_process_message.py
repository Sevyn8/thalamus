"""The one decision this service makes per message: ack or nack.

EVERYTHING ELSE IS AXON'S. The envelope, the adapter, the ledger and the send path are all tested
in axon/tests; what is left here is the routing, and the routing is the part that can lose a
message. An ack on a message that was not delivered removes the only copy; a nack on a message
that was delivered sends it again.

NO PUBSUB AND NO DATABASE. process_message takes an engine and an adapter and is driven with
fakes, so every branch is reachable offline. What that cannot cover is the pull loop's own
behaviour against a real subscription, which is the deployment's job.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import pytest
from axon import Channel, ChannelAdapter, DeliveryState, Message, SendOutcome, SendRequested
from axon_sender import subscriber as subscriber_module
from axon_sender.subscriber import process_message
from sqlalchemy.ext.asyncio import AsyncEngine

DELIVERY = UUID("019f9d6d-c032-7e03-a232-ee77299f9b5d")


def _engine() -> AsyncEngine:
    """A sentinel where an engine is expected, typed for mypy. Never touched: every test patches
    send_platform, which is the only thing that would open a connection."""
    return cast("AsyncEngine", object())


class _FakeAdapter:
    """An adapter that accepts everything. The provider's own failures are axon/tests' subject."""

    @property
    def channel(self) -> Channel:
        return Channel.EMAIL

    @property
    def provider(self) -> str:
        return "fake"

    async def send(self, message: Message) -> None:
        return None


def _envelope(**overrides: Any) -> SendRequested:
    fields: dict[str, Any] = {
        "delivery_id": DELIVERY,
        "channel": Channel.EMAIL,
        "recipient": "oncall@sevyn8.example",
        "subject": "a subject",
        "body": "a body",
        "notification_class": "synapse.provision.enabled",
        "subject_kind": "synapse.provision",
        "subject_id": "abc:stockout_risk",
        "actor_subject": "auth0|operator",
    }
    fields.update(overrides)
    return SendRequested(**fields)


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Capture the send AT THE MODULE subscriber.py calls it through.

    Patched here rather than at axon.send, because a test that patched the other name would pass
    against a consumer that had stopped calling it. Same trap every suite in this repository
    names, and the same fix.
    """

    def install(outcome: SendOutcome) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []

        async def fake_send(**kwargs: Any) -> SendOutcome:
            calls.append(kwargs)
            return outcome

        monkeypatch.setattr(subscriber_module, "send_platform", fake_send)
        return calls

    return install


def test_the_fake_adapter_satisfies_the_port() -> None:
    """THE VACUITY GUARD FOR EVERY TEST BELOW. A fake that had drifted from the Protocol would
    make all of them pass against a contract the real adapter does not share."""
    assert isinstance(_FakeAdapter(), ChannelAdapter)


async def test_a_recorded_send_is_acked(sent: Any) -> None:
    """THE HAPPY PATH. The ledger holds a row, so the message has done its job and the only copy
    can be released."""
    sent(SendOutcome(state=DeliveryState.ACCEPTED, recorded=True))

    decision = await process_message(engine=_engine(), adapter=_FakeAdapter(), raw=_envelope().to_json())

    assert decision == "ack"


async def test_a_recorded_failure_is_also_acked(sent: Any) -> None:
    """A PROVIDER REFUSAL IS EVIDENCE, NOT A REASON TO RETRY.

    state='failed' with the detail is a row somebody can count and act on, and a 403 replayed is
    another 403. Nacking here would burn the whole delivery budget on a message that cannot
    succeed and then dead-letter a delivery that IS already recorded, which would make the DLQ
    the wrong place to look for it.
    """
    sent(SendOutcome(state=DeliveryState.FAILED, recorded=True, detail="provider said 403"))

    decision = await process_message(engine=_engine(), adapter=_FakeAdapter(), raw=_envelope().to_json())

    assert decision == "ack"


async def test_a_duplicate_is_acked_without_a_second_row(sent: Any) -> None:
    """THE IDEMPOTENCY PATH, FROM THE CONSUMER'S SIDE.

    pk_platform_deliveries refused the INSERT because a previous attempt already wrote this
    delivery_id. The ledger is correct, so this pass acks and writes nothing. Nacking would loop
    a message that can never write a row again.
    """
    sent(SendOutcome(state=DeliveryState.ACCEPTED, recorded=True, duplicate=True))

    decision = await process_message(engine=_engine(), adapter=_FakeAdapter(), raw=_envelope().to_json())

    assert decision == "ack"


async def test_a_ledger_failure_is_nacked(sent: Any) -> None:
    """THE ONE NACK THAT IS NOT ABOUT THE MESSAGE, AND THE REASON THE QUEUE EXISTS.

    No row means nothing in the database says this was ever owed. Under slice 1 that was the end
    of it; now the message survives and the redelivery is what can still produce a row.

    IT IS ALSO THE DUPLICATE WINDOW. The send may already have happened, and on redelivery this
    path cannot know, so it sends again. That is the at-least-once residual, bounded by
    max_delivery_attempts = 5.
    """
    sent(SendOutcome(state=DeliveryState.ACCEPTED, recorded=False, detail="the ledger is down"))

    decision = await process_message(engine=_engine(), adapter=_FakeAdapter(), raw=_envelope().to_json())

    assert decision == "nack"


async def test_an_unreadable_envelope_is_nacked_not_acked(sent: Any) -> None:
    """ACKING WHAT CANNOT BE PARSED MAKES A PRODUCER BUG INVISIBLE.

    The messages would leave the queue and nothing anywhere would record that they existed. A
    nack sends them round the retry policy and into the dead-letter lane, where the alert fires
    and the bodies are readable for 31 days.
    """
    sent(SendOutcome(state=DeliveryState.ACCEPTED, recorded=True))

    decision = await process_message(engine=_engine(), adapter=_FakeAdapter(), raw=b"{not json at all")

    assert decision == "nack"


async def test_an_envelope_from_a_newer_producer_is_nacked(sent: Any) -> None:
    """VERSION SKEW IS A REAL STATE, not a hypothetical: the producer and this consumer are two
    images that deploy on separate schedules, so for a window they are different builds. A newer
    envelope is refused rather than partially read, and the refusal reaches the queue as a nack.
    """
    sent(SendOutcome(state=DeliveryState.ACCEPTED, recorded=True))
    body = _envelope().to_json().replace(b'"schema_version":1', b'"schema_version":9')

    decision = await process_message(engine=_engine(), adapter=_FakeAdapter(), raw=body)

    assert decision == "nack"


async def test_the_send_is_never_reached_when_the_envelope_is_unreadable(sent: Any) -> None:
    """THE ORDER MATTERS AND IS ASSERTED RATHER THAN READ. A parse failure that still called the
    send would hand the adapter fields it never validated."""
    calls = sent(SendOutcome(state=DeliveryState.ACCEPTED, recorded=True))

    await process_message(engine=_engine(), adapter=_FakeAdapter(), raw=b"[]")

    assert calls == []


async def test_the_envelopes_delivery_id_is_what_reaches_the_send(sent: Any) -> None:
    """THE WHOLE IDEMPOTENCY CHAIN IN ONE ASSERTION.

    The producer minted it, it survived the wire, and it must reach send_platform unchanged: that
    is what makes a redelivery hit the same primary key. A consumer that minted its own here
    would break idempotency while every other test in this file still passed.
    """
    calls = sent(SendOutcome(state=DeliveryState.ACCEPTED, recorded=True))

    await process_message(engine=_engine(), adapter=_FakeAdapter(), raw=_envelope().to_json())

    assert calls[0]["delivery_id"] == DELIVERY


async def test_a_channel_with_no_adapter_is_nacked(sent: Any) -> None:
    """A GUARD AGAINST A FUTURE PRODUCER, not a live branch: the platform ledger CHECK-forces
    email, so nothing can produce a whatsapp send today. It nacks rather than pretending, and it
    says so one layer earlier than the adapter would.
    """
    calls = sent(SendOutcome(state=DeliveryState.ACCEPTED, recorded=True))
    body = _envelope().to_json().replace(b'"channel":"email"', b'"channel":"whatsapp"')

    decision = await process_message(engine=_engine(), adapter=_FakeAdapter(), raw=body)

    assert decision == "nack"
    assert calls == []
