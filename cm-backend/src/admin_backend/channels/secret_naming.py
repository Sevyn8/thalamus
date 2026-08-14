"""The Secret Manager name for one tenant's credential on one channel.

=================================================================================================
THIS RULE LIVES IN CUSTOMER MASTER ALONE, AND THAT IS THE DECISION RATHER THAN AN ACCIDENT
=================================================================================================
Axon shipped a shared ``axon.vault.secret_id_for`` in slice 4 so that both the writer and the
reader could derive the same name. It had one caller and was deleted in slice 5. cm-backend is
not a uv workspace member and its Dockerfile builds from ``cm-backend/`` with no path to
``axon/``, so the writer could never import it; a "shared" function only one side can call is
two definitions waiting to disagree.

So the coupling moved to data. CM derives the name, writes the secret, and RECORDS the name in
``axon.channel_connections.secret_ref``. Axon reads that column verbatim and derives nothing.
Nothing outside this module needs to reproduce the format, which means the format can change
without a second deployment agreeing to change with it.

=================================================================================================
DETERMINISM IS STILL REQUIRED, AND FOR EXACTLY ONE REASON WORTH WRITING DOWN
=================================================================================================
The Secret Manager write and the Postgres row write CANNOT BE ATOMIC. They are two systems.
The write path orders them so the row is written first into the open request transaction and the
secret last, so a failed secret write rolls the row back and leaves nothing behind. That closes
one direction and not the other: if the secret write SUCCEEDS and the transaction's final COMMIT
then fails, the secret exists and the row does not.

With a deterministic name that is recoverable. The retry derives the SAME name, the create is an
AlreadyExists no-op, a version is added, and the row lands. With a random name the retry mints a
SECOND secret and the first holds a live tenant credential that nothing can ever attribute to a
tenant or a channel again: not by listing, not by joining, not by reading it. That is the whole
argument, and it is about orphan attribution rather than about tidiness.

The same property makes a reconciliation sweep possible at all. Every ``axon-channel-*`` secret
in the project parses back to a (tenant, channel) pair, so "which secrets have no row" is a
question somebody can answer. No sweep is built in this slice; the name is what leaves the door
open.
"""

from __future__ import annotations

from uuid import UUID

__all__ = ["secret_id_for"]

# Distinguishes Axon's channel credentials from every other vault in this project
# (square-oauth-*, clover-oauth-*) in one flat namespace where the only grouping is the name.
_PREFIX = "axon-channel"


def secret_id_for(tenant_id: UUID, channel: str) -> str:
    """The deterministic Secret Manager secret id for one tenant's channel credential.

    Shape: ``axon-channel-{tenant_uuid}-{channel}``. Longest value with the channel vocabulary
    the ledger's CHECK permits (``email``, ``whatsapp``, ``sms``) is 58 characters, well inside
    Secret Manager's 255 limit, and every character is in the legal ``[A-Za-z0-9_-]`` set without
    sanitising: the prefix is literal, a UUID's string form is hex and hyphens, and the channel
    vocabulary is lowercase ASCII.

    NO HASH SUFFIX, unlike ``thalamus_square_oauth.naming.secret_id_for``, and the absence is
    reasoned rather than forgotten. That module sanitises its second axis and appends
    ``sha1(raw)[:8]`` because ``source_id`` is up to 128 arbitrary characters and two of them can
    collide after sanitising. This second axis is a closed three-value vocabulary that cannot
    collide with itself and cannot need sanitising, so a hash would encode one of three constants
    in eight characters and make the name unreadable in a console listing for nothing.

    ``channel`` IS VALIDATED HERE rather than trusted. The caller holds a value that reached it
    from a request, and a name is the one artifact that must never be wrong: a mistyped channel
    produces a stable, legal-looking name pointing at a secret nothing will ever look for.
    """
    if channel not in _LEGAL_CHANNELS:
        raise ValueError(
            f"channel {channel!r} is not one of {sorted(_LEGAL_CHANNELS)}. The secret name is "
            "the only handle on a stored credential; deriving one from an unrecognised channel "
            "would produce a name that looks correct and that nothing will ever resolve."
        )
    return f"{_PREFIX}-{tenant_id}-{channel}"


# The ledger's ck_tenant_deliveries_channel_vocab and channel_connections'
# ck_channel_connections_channel_vocab both name exactly these three. Kept here as a frozenset
# rather than imported from a shared enum because cm-backend cannot import axon; the test asserts
# this set against the DDL text, which IS readable from here.
_LEGAL_CHANNELS = frozenset({"email", "whatsapp", "sms"})
