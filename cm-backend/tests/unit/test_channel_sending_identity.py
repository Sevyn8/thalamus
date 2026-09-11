"""The sending identity is checked against the channel, and only where the shape is knowable.

THE DEFECT. A channel_connections row was saved with channel=email and
sending_identity=9560879222. Nothing refused it: the field carried a length cap and no format
rule. A From address that is a phone number cannot send, and the tenant was told the channel was
configured.

WHY THE THIRD CASE IN THIS FILE IS THE IMPORTANT ONE. Rejecting a phone number on email and
accepting an address on email would both pass under a GLOBAL email rule, and a global rule would
be a worse defect than the one being fixed: it would refuse every legitimate sms sender id and
whatsapp number. So the same phone number that email refuses is asserted ACCEPTED on sms. That
is what makes the rule per-channel rather than merely present.

WHY SMS AND WHATSAPP HAVE NO FORMAT RULE AT ALL. Both an E.164 number and an alphanumeric sender
id are legitimate; which one a tenant may use is the provider's rule, and this repository has no
provider contract and no adapter for either channel to read one from. A guessed pattern would
refuse valid input with a confident message.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from admin_backend.schemas.channel import ChannelUpsertRequest

_THE_PHONE_NUMBER = "9560879222"


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "channel": "email",
        "provider": "sinch",
        "credential": [{"key": "api_key", "value": "x"}],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# email: the one channel whose shape the code establishes
# ---------------------------------------------------------------------------


def test_a_phone_number_is_refused_as_an_email_sending_identity() -> None:
    """THE ROW THAT WAS ACTUALLY SAVED. Same channel and same value."""
    with pytest.raises(ValidationError) as caught:
        ChannelUpsertRequest.model_validate(
            _payload(channel="email", sending_identity=_THE_PHONE_NUMBER)
        )

    message = str(caught.value)
    assert "sending_identity" in message
    assert "email address" in message, (
        "the refusal must say what is wrong with the value, not merely that it is invalid"
    )


@pytest.mark.parametrize(
    "identity",
    ["billing@tenant.example", "Billing Team <billing@tenant.example>", "a@b.co"],
)
def test_an_email_sending_identity_that_is_an_address_is_accepted(identity: str) -> None:
    """The happy path, and it includes the display-name form because a From header legitimately
    carries one. If EmailStr ever stops accepting that shape this fails rather than silently
    refusing a form tenants use."""
    model = ChannelUpsertRequest.model_validate(
        _payload(channel="email", sending_identity=identity)
    )
    assert model.sending_identity == identity


# ---------------------------------------------------------------------------
# sms and whatsapp: no format rule, deliberately
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("channel", ["sms", "whatsapp"])
def test_the_same_phone_number_is_accepted_on_sms_and_whatsapp(channel: str) -> None:
    """THE PER-CHANNEL PROOF, and the reason this file exists rather than a single sad-path test.

    This is the exact value that email refuses, on the channels where it is correct. A global
    email rule would pass both tests above and fail here, and it would be a worse defect than the
    one being fixed: every legitimate sms sender id and whatsapp number would be refused with a
    confident message about email addresses.
    """
    model = ChannelUpsertRequest.model_validate(
        _payload(channel=channel, sending_identity=_THE_PHONE_NUMBER)
    )
    assert model.sending_identity == _THE_PHONE_NUMBER


@pytest.mark.parametrize("channel", ["sms", "whatsapp"])
@pytest.mark.parametrize("identity", ["+919560879222", "SEVYN8", "Acme Ltd", "12345"])
def test_sms_and_whatsapp_accept_every_shape_a_provider_might_issue(
    channel: str, identity: str
) -> None:
    """E.164, an alphanumeric sender id, one with a space, and a short code. All are real shapes
    somebody issues, none is checkable from this repository, and none is refused."""
    model = ChannelUpsertRequest.model_validate(
        _payload(channel=channel, sending_identity=identity)
    )
    assert model.sending_identity == identity


# ---------------------------------------------------------------------------
# What every channel gets
# ---------------------------------------------------------------------------


def test_the_identity_is_trimmed_on_every_channel() -> None:
    model = ChannelUpsertRequest.model_validate(
        _payload(channel="sms", sending_identity="  SEVYN8  ")
    )
    assert model.sending_identity == "SEVYN8"


def test_a_trimmed_email_address_still_passes_the_email_rule() -> None:
    """Ordering: the trim has to happen BEFORE the email check, or a pasted address with a
    trailing space is refused for being a bad address rather than tidied."""
    model = ChannelUpsertRequest.model_validate(
        _payload(channel="email", sending_identity=" billing@tenant.example ")
    )
    assert model.sending_identity == "billing@tenant.example"


@pytest.mark.parametrize("channel", ["email", "sms", "whatsapp"])
def test_a_whitespace_only_identity_becomes_absent_rather_than_blank(channel: str) -> None:
    """Stored as "   " it renders as an empty cell that reads as set. None is the honest value,
    and on email it also means whitespace is not put through the address check."""
    model = ChannelUpsertRequest.model_validate(
        _payload(channel=channel, sending_identity="   ")
    )
    assert model.sending_identity is None


@pytest.mark.parametrize("channel", ["email", "sms", "whatsapp"])
def test_the_identity_remains_optional_on_every_channel(channel: str) -> None:
    """A connection can exist before the provider has issued an identity; the DDL column is
    NULLABLE for that reason (axon/schemas/postgres/channels.sql). Omitting it must not become a
    validation error as a side effect of adding one."""
    model = ChannelUpsertRequest.model_validate(_payload(channel=channel))
    assert model.sending_identity is None
