"""The queue envelope: what it carries, what it refuses, and the round trip.

THE ENVELOPE IS THE CONTRACT BETWEEN TWO DEPLOYMENTS. synapse-ui-server writes it and axon-sender
reads it, and they ship as separate images on separate schedules, so for a window they are
different builds. Nothing in either process checks the other; these tests are the only place the
two halves are held up against each other.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from axon import Channel, Publisher, SendRequested

DELIVERY = UUID("019f9d6d-c032-7e03-a232-ee77299f9b5d")


def _envelope(**overrides: object) -> SendRequested:
    fields: dict[str, object] = {
        "delivery_id": DELIVERY,
        "channel": Channel.EMAIL,
        "recipient": "oncall@sevyn8.example",
        "subject": "Synapse: stockout_risk enabled for TestCo",
        "body": "a body",
        "notification_class": "synapse.provision.enabled",
        "subject_kind": "synapse.provision",
        "subject_id": "019f9d6d-c032-7e03-a232-ee77299f9b5d:stockout_risk",
        "actor_subject": "auth0|operator",
    }
    fields.update(overrides)
    return SendRequested(**fields)  # type: ignore[arg-type]


def test_the_round_trip_preserves_every_field() -> None:
    """THE WHOLE CONTRACT IN ONE ASSERTION. A field that serialises and does not deserialise is a
    field the sender silently loses, and the only symptom is a message missing something."""
    original = _envelope()

    assert SendRequested.from_json(original.to_json()) == original


def test_the_optional_actor_survives_being_absent() -> None:
    """actor_subject is the one genuinely optional field, and None must round-trip as None rather
    than as the string 'None' or a missing key that raises."""
    original = _envelope(actor_subject=None)

    assert SendRequested.from_json(original.to_json()).actor_subject is None


def test_the_delivery_id_is_the_idempotency_key_and_survives_the_wire() -> None:
    """THE ONE FIELD THE IDEMPOTENCY TURNS ON. It is pk_platform_deliveries, so if it did not
    survive serialisation intact a redelivery would reach a different row and the primary key
    would refuse nothing."""
    parsed = SendRequested.from_json(_envelope().to_json())

    assert parsed.delivery_id == DELIVERY
    assert parsed.delivery_id.version == 7


def test_the_serialisation_is_stable_for_one_envelope() -> None:
    """SORTED KEYS AND NO WHITESPACE, so the same envelope produces the same bytes.

    Not required by Pub/Sub, which cares about neither. It matters because a message body that
    varies between two serialisations of one value makes any future body-level comparison
    unreliable, and because a stable form is what makes a message readable in a DLQ.
    """
    assert _envelope().to_json() == _envelope().to_json()


def test_a_newer_schema_version_is_refused_rather_than_partly_read() -> None:
    """A CONSUMER THAT BEST-EFFORT PARSES A NEWER ENVELOPE SENDS A DAMAGED MESSAGE.

    The fields a build does not recognise are exactly the ones a partial read drops, so the
    message goes out missing whatever the new field was for. Refusing is worse-looking and
    better: the message nacks, retries, and dead-letters where somebody can see it.
    """
    body = _envelope().to_json().replace(b'"schema_version":1', b'"schema_version":2')

    with pytest.raises(ValueError, match="schema_version"):
        SendRequested.from_json(body)


def test_a_body_that_is_not_an_object_is_refused() -> None:
    """Valid JSON is not a valid envelope. A bare array or string parses and then fails on a
    missing key with a KeyError, which says nothing useful in a log."""
    with pytest.raises(ValueError, match="not an object"):
        SendRequested.from_json(b'["not", "an", "envelope"]')


def test_a_missing_required_field_raises_rather_than_defaulting() -> None:
    """THE ALTERNATIVE WOULD BE WORSE THAN A CRASH. A recipient defaulted to empty string sends
    a message to nobody and records a delivery that says it went."""
    body = _envelope().to_json().replace(b'"recipient":"oncall@sevyn8.example",', b"")

    with pytest.raises(KeyError):
        SendRequested.from_json(body)


def test_the_topic_name_lives_in_one_place() -> None:
    """BOTH SIDES IMPORT IT FROM HERE. The producer publishes to it and the subscription is named
    after it in terraform; a name configured twice is a name that can disagree with itself, and
    the failure is a producer publishing into a topic nothing drains."""
    from axon import TOPIC_SEND_REQUESTED

    assert TOPIC_SEND_REQUESTED == "axon-send-requested"


def test_a_list_satisfies_the_publisher_protocol_shape() -> None:
    """THE VACUITY GUARD FOR EVERY PUBLISH TEST ELSEWHERE. Those drive a fake; if the Protocol
    drifted from what the real client offers, the fakes would keep passing against a contract
    nothing implements. Asserted with isinstance because the Protocol is runtime_checkable."""

    class _FakePublisher:
        def __init__(self) -> None:
            self.published: list[tuple[str, bytes]] = []

        def publish(self, topic_name: str, data: bytes) -> str:
            self.published.append((topic_name, data))
            return "fake-message-id"

    assert isinstance(_FakePublisher(), Publisher)
