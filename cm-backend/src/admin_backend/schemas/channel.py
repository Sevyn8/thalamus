"""Request and response shapes for tenant sending channels.

THE CREDENTIAL IS KEY-VALUE PAIRS RATHER THAN NAMED FIELDS, AND THAT IS AN ADMISSION.
The provider is Sinch and the values in hand are a client id, a username and a password, which
match none of Sinch's documented current APIs. Naming three fields in a Pydantic model would
freeze that guess into a 422 and into a migration; a tenant whose provider hands them different
values would be unable to enter them at all. So the model validates SHAPE and never semantics,
and the surface tells the tenant to enter what their provider gave them.

NOTHING IN THIS MODULE EVER CARRIES THE CREDENTIAL BACK OUT. There is a request shape with
values in it and a response shape without one. That is not an oversight to be tidied into
symmetry: the read path has no way to obtain a value (the service's IAM role omits
versions.access), and a response model with a field for one would be the first step toward
acquiring the ability.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

__all__ = [
    "ChannelConnectionRead",
    "ChannelConnectionsListResponse",
    "ChannelCredentialPair",
    "ChannelUpsertRequest",
    "PlatformChannelConnectionRead",
    "PlatformChannelConnectionsListResponse",
]

# Keys are identifiers a tenant retypes from a provider console, so the charset is deliberately
# permissive within what stays readable in a JSON object and a log line: letters, digits and the
# three separators every provider uses. No spaces, so a trailing space cannot silently produce a
# second distinct key.
_KEY_PATTERN = r"^[A-Za-z0-9_.-]{1,64}$"

# One credential blob, serialised. Generous for a handful of tokens and far below Secret
# Manager's 64 KiB payload limit; its purpose is to refuse a paste of something that is not a
# credential at all rather than to be a tight bound.
_MAX_BLOB_BYTES = 8192

# Enough for any real credential set and low enough that the form stays a form.
_MAX_PAIRS = 20

# EmailStr behind a TypeAdapter rather than as a field type, because the field is only an email
# address on ONE of the three channels. Declaring the field as EmailStr would refuse an sms
# sender id, and declaring it as str with no check is what let a phone number onto an email
# channel. The adapter lets the model validator apply the rule exactly where it holds.
_EMAIL_ADAPTER: TypeAdapter[EmailStr] = TypeAdapter(EmailStr)


class ChannelCredentialPair(BaseModel):
    """One key and one value, both the tenant's words."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=_KEY_PATTERN)
    value: str = Field(min_length=1, max_length=4096)


class ChannelUpsertRequest(BaseModel):
    """Configure or reconfigure one channel.

    REPLACES THE WHOLE CREDENTIAL SET. There is no partial edit, because a partial edit would
    require reading the stored set to merge into, and nothing here can read it. The surface says
    so in as many words rather than letting a tenant discover it by losing a value.
    """

    model_config = ConfigDict(extra="forbid")

    channel: str = Field(description="email, whatsapp or sms")
    provider: str = Field(min_length=1, max_length=32)
    sending_identity: str | None = Field(
        default=None,
        max_length=255,
        description=(
            "Who the message appears to come from, which is a different kind of value per "
            "channel: a From address on email, and a number or sender id on sms and whatsapp. "
            "An identifier, not a secret: Sevyn8 support can see this, unlike the credential. "
            "Only the email form is checked; see the validator for why the other two are not."
        ),
    )
    credential: list[ChannelCredentialPair] = Field(min_length=1, max_length=_MAX_PAIRS)

    @field_validator("channel")
    @classmethod
    def _known_channel(cls, v: str) -> str:
        """The ledger's CHECK vocabulary, refused here so the failure is a 422 naming the field
        rather than a database error naming a constraint."""
        if v not in ("email", "whatsapp", "sms"):
            raise ValueError("channel must be one of: email, sms, whatsapp")
        return v

    @field_validator("credential")
    @classmethod
    def _keys_unique_and_blob_bounded(
        cls, v: list[ChannelCredentialPair]
    ) -> list[ChannelCredentialPair]:
        """Two shape rules that a per-item validator cannot see.

        DUPLICATE KEYS ARE REFUSED rather than last-wins. The blob is stored as a JSON object, so
        a duplicate silently drops one of the tenant's values, and the value it drops is invisible
        from the form. Refusing is the only outcome that cannot lose a credential quietly.
        """
        keys = [pair.key for pair in v]
        duplicates = sorted({k for k in keys if keys.count(k) > 1})
        if duplicates:
            raise ValueError(f"duplicate credential keys: {', '.join(duplicates)}")

        blob = json.dumps({pair.key: pair.value for pair in v}, separators=(",", ":"))
        if len(blob.encode("utf-8")) > _MAX_BLOB_BYTES:
            raise ValueError(f"credential exceeds {_MAX_BLOB_BYTES} bytes when serialised")
        return v

    @model_validator(mode="after")
    def _sending_identity_fits_the_channel(self) -> ChannelUpsertRequest:
        """Check the sending identity against the channel, but ONLY where the shape is knowable.

        =========================================================================================
        WHAT WENT WRONG WITHOUT THIS
        =========================================================================================
        On 2026-08-15 a row was saved with channel=email and sending_identity=9560879222. Nothing
        refused it: the field carried a length cap and no format rule, and the surface's helper
        text was phone-shaped for all three channels, so it read as an invitation. A From address
        that is a phone number cannot send, and the tenant is told the channel is configured.

        =========================================================================================
        EMAIL IS CHECKED. SMS AND WHATSAPP ARE DELIBERATELY NOT.
        =========================================================================================
        The email case is knowable: the identity IS a From address, so it is an email address,
        and EmailStr is already this codebase's answer to that question (schemas/tenant_user.py,
        schemas/tenant.py).

        For sms and whatsapp it is NOT knowable from this repository. Both an E.164 number and an
        alphanumeric sender id are legitimate, which of them a tenant may use is the provider's
        rule, and no provider contract and no adapter for either channel exists here to read one
        from. A guessed pattern would refuse valid input with a confident message, which is a
        worse defect than the one above: the tenant cannot tell a real rule from our invention.

        SO THE DEFAULT FOR AN UNRECOGNISED CHANNEL IS NO FORMAT RULE, NOT A GUESS. Unreachable
        today because _known_channel refuses anything outside the three before this runs, and
        written this way so a fourth channel arrives unvalidated rather than mis-validated.

        WHAT IS CHECKED FOR EVERY CHANNEL is only that a value is not whitespace: an identity of
        "   " is stored as absent rather than as a string that renders blank and looks set.
        """
        if self.sending_identity is None:
            return self

        trimmed = self.sending_identity.strip()
        if not trimmed:
            # Whitespace only. Absent is the honest reading, and it keeps the surface from
            # showing a set-looking blank.
            self.sending_identity = None
            return self
        self.sending_identity = trimmed

        if self.channel == "email":
            try:
                _EMAIL_ADAPTER.validate_python(trimmed)
            except ValueError as exc:
                raise PydanticCustomError(
                    "sending_identity_not_an_email",
                    (
                        "sending_identity must be an email address when channel is email. "
                        "It is the From address recipients will see."
                    ),
                ) from exc

        return self

    def credential_blob(self) -> bytes:
        """The bytes that go into Secret Manager. Sorted keys, so re-entering the same credential
        produces the same payload and a diff of two versions is readable."""
        return json.dumps(
            {pair.key: pair.value for pair in self.credential},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")


class ChannelConnectionRead(BaseModel):
    """One connection, as the owning tenant sees it. NO CREDENTIAL FIELD, by design."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    channel: str
    provider: str
    status: str = Field(
        description=(
            "pending, connected or disabled. Only pending is reachable today: connected means a "
            "send was accepted on this channel, and no adapter exists yet to accept one."
        )
    )
    sending_identity: str | None
    secret_ref: str | None = Field(
        description="The Secret Manager secret NAME. Never the credential's value."
    )
    connected_at: datetime | None
    disabled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ChannelConnectionsListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ChannelConnectionRead]


class PlatformChannelConnectionRead(ChannelConnectionRead):
    """The same row plus the tenant it belongs to, for the operator surface.

    Adding ``tenant_id`` here rather than giving the platform read its own unrelated shape keeps
    one promise in one place: whatever the tenant surface cannot show, this cannot either.
    """

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    tenant_id: UUID


class PlatformChannelConnectionsListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PlatformChannelConnectionRead]
