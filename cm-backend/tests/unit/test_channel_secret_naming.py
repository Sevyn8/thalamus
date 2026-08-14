"""The secret name: the only handle on a stored tenant credential.

WHY THIS IS TESTED HARDER THAN ITS SIZE SUGGESTS. The Secret Manager write and the Postgres row
write cannot be atomic. If the secret lands and the row does not, the name is the ONLY thing that
can ever attribute that credential to a tenant and a channel again, and the only thing that makes
the retry land on the same secret instead of minting a second one. A wrong name is not a cosmetic
defect here; it is an unattributable live credential.
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

import pytest

from admin_backend.channels import secret_id_for

_TENANT = UUID("019ffff2-990d-7666-b2b6-1095facbd290")

# Secret Manager's own rule: [A-Za-z0-9_-], 1 to 255 characters.
_LEGAL_SECRET_ID = re.compile(r"^[A-Za-z0-9_-]{1,255}$")

_CHANNELS = ("email", "whatsapp", "sms")


def test_the_name_is_stable_for_the_same_inputs() -> None:
    """THE WHOLE CONTRACT. A retry after a failed commit must derive the same string, or it
    creates a second secret and orphans the first."""
    assert secret_id_for(_TENANT, "whatsapp") == secret_id_for(_TENANT, "whatsapp")


def test_the_name_is_pinned_as_a_literal() -> None:
    """PINNED, not recomputed from the same f-string the implementation uses. A test that rebuilds
    the format it is checking passes against any format."""
    assert (
        secret_id_for(_TENANT, "whatsapp")
        == "axon-channel-019ffff2-990d-7666-b2b6-1095facbd290-whatsapp"
    )


@pytest.mark.parametrize("channel", _CHANNELS)
def test_every_channel_produces_a_legal_secret_id(channel: str) -> None:
    name = secret_id_for(_TENANT, channel)
    assert _LEGAL_SECRET_ID.match(name), f"{name!r} is not a legal Secret Manager id"


def test_two_channels_for_one_tenant_do_not_collide() -> None:
    """One tenant may configure WhatsApp and SMS with different credentials. A name ignoring the
    channel would make the second save overwrite the first."""
    assert secret_id_for(_TENANT, "sms") != secret_id_for(_TENANT, "whatsapp")


def test_two_tenants_on_one_channel_do_not_collide() -> None:
    """THE WORST OUTCOME AVAILABLE HERE: one tenant's credential in another tenant's vault
    entry."""
    other = UUID("019f9d6d-c032-7e03-a232-ee77299f9b5d")
    assert secret_id_for(_TENANT, "whatsapp") != secret_id_for(other, "whatsapp")


@pytest.mark.parametrize("channel", ["", "WHATSAPP", "whats app", "voice", "whatsapp ", "sms;"])
def test_an_unrecognised_channel_is_refused_rather_than_named(channel: str) -> None:
    """A MISTYPED CHANNEL PRODUCES A STABLE, LEGAL-LOOKING NAME POINTING AT NOTHING.

    That is the failure mode worth refusing: it does not raise, it does not look wrong, and the
    credential is written under a name no reader will ever ask for. Case matters too, because
    Secret Manager names are case-sensitive while the channel vocabulary is lowercase.
    """
    with pytest.raises(ValueError, match="channel"):
        secret_id_for(_TENANT, channel)


def test_the_channel_vocabulary_matches_axons_ddl() -> None:
    """CM CANNOT IMPORT AXON, so the vocabulary is duplicated here as a frozenset. That makes it a
    second definition, and this is what holds the two equal: it reads Axon's DDL as TEXT, which is
    reachable across the repository even though the package is not importable.

    If Axon adds a channel and CM does not, a tenant configuring it gets a 422 from a service that
    should have accepted it. If CM adds one Axon does not have, the row fails its CHECK at write
    time. Both are quiet in different ways.
    """
    ddl = (
        Path(__file__).resolve().parents[2].parent
        / "axon"
        / "schemas"
        / "postgres"
        / "channels.sql"
    )
    assert ddl.is_file(), f"{ddl} not found; this test compares against Axon's DDL text"
    check = "CHECK (channel IN ('email', 'whatsapp', 'sms'))"
    assert check in ddl.read_text(encoding="utf-8"), (
        "axon's channel vocabulary changed. CM's _LEGAL_CHANNELS in channels/secret_naming.py "
        "must change with it, or the two disagree about what a tenant may configure."
    )
    for channel in _CHANNELS:
        secret_id_for(_TENANT, channel)  # every DDL-legal channel must be nameable here
