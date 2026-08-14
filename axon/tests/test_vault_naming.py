"""The secret name, which is the only thing joining a writer and a reader in two processes.

WHY THIS FILE IS THE ONLY CALLER TODAY, AND WHY THAT IS STILL WORTH TESTING. The writer is a
tenant-facing form that does not exist and the reader is a Sinch adapter that does not exist.
What these tests protect is the property that makes the function worth landing first: that the
name is a pure function of two typed inputs, so the second side written cannot invent its own.

WHAT THEY CANNOT PROTECT is the thing the module's docstring admits: cm-backend cannot import
this module (it is outside the uv workspace and its Dockerfile builds from cm-backend/), so
nothing mechanical will hold the CM half to this function. No test here can fix that.
"""

from __future__ import annotations

import re
from uuid import UUID

import pytest
from axon import Channel, secret_id_for

_TENANT = UUID("019f9d6d-c032-7e03-a232-ee77299f9b5d")

# Secret Manager's own rule: [A-Za-z0-9_-], 1 to 255 characters.
_LEGAL_SECRET_ID = re.compile(r"^[A-Za-z0-9_-]{1,255}$")


def test_the_name_is_stable_for_the_same_inputs() -> None:
    """THE WHOLE CONTRACT. A writer and a reader in different processes must derive the same
    string, so the function may not depend on anything but its arguments."""
    assert secret_id_for(_TENANT, Channel.WHATSAPP) == secret_id_for(_TENANT, Channel.WHATSAPP)


def test_the_name_is_exactly_what_both_sides_will_look_for() -> None:
    """PINNED AS A LITERAL, not recomputed from the same f-string this test is checking. A test
    that rebuilds the format it is verifying passes against any format."""
    assert (
        secret_id_for(_TENANT, Channel.WHATSAPP)
        == "axon-channel-019f9d6d-c032-7e03-a232-ee77299f9b5d-whatsapp"
    )


@pytest.mark.parametrize("channel", list(Channel))
def test_every_channel_produces_a_legal_secret_id(channel: Channel) -> None:
    """PARAMETRISED OVER THE ENUM rather than a hand-written list, so a fourth channel is
    covered the day it is declared instead of the day somebody remembers this file."""
    name = secret_id_for(_TENANT, channel)
    assert _LEGAL_SECRET_ID.match(name), f"{name!r} is not a legal Secret Manager id"


@pytest.mark.parametrize("channel", list(Channel))
def test_no_channel_needs_sanitizing(channel: Channel) -> None:
    """THE JUSTIFICATION FOR OMITTING SQUARE'S HASH SUFFIX, ASSERTED RATHER THAN ASSUMED.

    square-oauth's naming module sanitizes and appends sha1(raw)[:8] because its second axis is
    128 arbitrary characters that can collide after sanitizing. This one's second axis is a
    closed vocabulary of lowercase ASCII words, so there is nothing to sanitize and a hash would
    encode one of three constants. If a channel value ever stopped being URL-safe, this test is
    what would notice before the hash's absence became a collision.
    """
    assert re.match(r"^[a-z]+$", str(channel)), (
        f"channel {channel!r} is no longer plain lowercase ASCII, so the name now needs the "
        "sanitize-and-hash step that square-oauth's module carries and this one deliberately omits"
    )


def test_two_channels_for_one_tenant_do_not_collide() -> None:
    """One tenant may have WhatsApp and SMS connected at once, with different credentials. A
    name that ignored the channel would make the second write overwrite the first."""
    assert secret_id_for(_TENANT, Channel.SMS) != secret_id_for(_TENANT, Channel.WHATSAPP)


def test_two_tenants_on_one_channel_do_not_collide() -> None:
    """THE FAILURE THIS WOULD BE. Two tenants sharing a secret name means one tenant's
    credential in another tenant's vault entry, which is the worst outcome available here."""
    other = UUID("019fb16b-e402-7dce-b026-6fa9f4919242")
    assert secret_id_for(_TENANT, Channel.WHATSAPP) != secret_id_for(other, Channel.WHATSAPP)


def test_the_name_stays_inside_secret_managers_length_limit() -> None:
    """A UUID is fixed-width and the channel is bounded by the longest enum member, so this is
    a constant rather than a range. Asserted so a future prefix change cannot quietly approach
    the 255 limit."""
    longest = max((secret_id_for(_TENANT, c) for c in Channel), key=len)
    assert len(longest) <= 255
    assert len(longest) == 58, (
        f"the longest name is now {len(longest)} characters. That is not a failure by itself, "
        "but the docstring states 58 and a docstring that disagrees with the code is the defect "
        "this repository keeps paying for."
    )
