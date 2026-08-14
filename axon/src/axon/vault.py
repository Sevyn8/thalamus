"""The Secret Manager name for one tenant's credential on one channel.

WHAT THIS EXISTS TO PREVENT. A per-tenant credential is written by one process and read by
another, and the only thing joining them is the name of the secret. A name composed
independently on each side is a name that can disagree with itself, and the failure is
silent in the worst way: the writer succeeds, the reader gets NotFound, and the channel
reads as unconfigured for a tenant that configured it. So the name is a function, and both
sides are meant to call it rather than format a string.

=================================================================================================
THIS FUNCTION HAS NO RUNTIME CALLER IN THE SLICE THAT INTRODUCED IT, AND THAT IS AN ACCEPTED
EXCEPTION RATHER THAN AN OVERSIGHT
=================================================================================================
It exists to PRE-EXIST both callers. The writer is the tenant-facing form, which does not
exist; the reader is the Sinch adapter, which does not exist. Landing the definition first is
the only ordering in which the second one written cannot invent its own.

AND THE CLAIM "THE NAME CANNOT DRIFT" IS TODAY AN ASPIRATION RATHER THAN A PROPERTY.
The writer is Customer Master: a tenant administrator types the credential into CM, so CM's
runtime service account is what creates the secret. CM CANNOT IMPORT THIS MODULE.
cm-backend is not a member of the uv workspace, it carries its own uv.lock, and its Dockerfile
builds from the cm-backend/ directory with no path to axon/. Nothing in the build reaches this
file. Until that changes, the two sides agreeing is a thing somebody has to keep true by hand,
which is exactly the property this module was supposed to remove.

Stated here rather than only in a report, because the person who writes the CM half will read
this docstring and not that report. When the CM-side write lands, its slice has to either move
cm-backend into the workspace or accept a second copy, and the second copy is the thing this
file was written to make unnecessary.

=================================================================================================
SHAPED ON THE SQUARE CONNECTOR, MINUS ONE THING IT NEEDS AND THIS DOES NOT
=================================================================================================
connectors/square-oauth/src/thalamus_square_oauth/naming.py sanitizes its second axis to the
legal charset and appends sha1(raw)[:8], because ``source_id`` is up to 128 arbitrary
characters and two of them can sanitize onto one slug.

NO HASH HERE, AND THE ABSENCE IS REASONED. The second axis is ``channel``, which is a closed
three-value vocabulary already constrained to lowercase ASCII by the ledger's CHECK. It cannot
collide with itself and it cannot need sanitizing, so a hash suffix would encode one of three
constants in eight characters and make the name unreadable in a console listing for nothing.
If a future axis is ever free text, it brings the hash back with it.

THE VALUE IS AN OPAQUE BLOB, AND THAT IS A DECISION ABOUT THE PAYLOAD RATHER THAN THE NAME.
The provider is Sinch and the auth shape is UNKNOWN: the fields in hand are a client id, a
username and a password, which match none of Sinch's documented current APIs, and whether they
exchange for a short-lived token is unestablished. Storing named fields would freeze a guess
into a schema. A blob means the adapter's needs can change without a migration.
"""

from __future__ import annotations

from uuid import UUID

from axon.channel import Channel

__all__ = ["secret_id_for"]

# Distinguishes Axon's secrets from every other vault in this project (square-oauth-*,
# clover-oauth-*) in one flat namespace where the only grouping is the name.
_PREFIX = "axon-channel"


def secret_id_for(tenant_id: UUID, channel: Channel) -> str:
    """The deterministic Secret Manager secret id for one tenant's channel credential.

    Shape: ``axon-channel-{tenant_uuid}-{channel}``. Longest possible value is 58 characters,
    well inside Secret Manager's 255 limit, and every character is in the legal
    ``[A-Za-z0-9_-]`` set without sanitizing: the prefix is literal, a UUID's string form is
    hex and hyphens, and ``Channel`` is a StrEnum of lowercase ASCII words.

    TAKES A ``Channel`` RATHER THAN A ``str``, so a caller cannot pass "WhatsApp" or "whatsap"
    and produce a name that is stable, wrong, and indistinguishable from a correct one until
    something looks for it. The type is the validation.
    """
    return f"{_PREFIX}-{tenant_id}-{channel}"
