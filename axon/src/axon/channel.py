"""The Channel port: one send operation, one adapter per provider per channel.

THIS IS CM'S ``EmailSender`` PROTOCOL WIDENED BY A CHANNEL DISCRIMINATOR, not a new design.
``cm-backend/src/admin_backend/email_sender.py`` already ships a working SendGrid v3 client
behind a ``runtime_checkable`` Protocol with one method, and everything it learned carries:
construction guarded on the credential, a typed error rather than a raw 500, click tracking
disabled in code with a recorded reason, and the test suite never reaching the real provider.

WHAT THE WIDENING IS. CM's Protocol is ``send_email(to, subject, body)``: email is assumed in
the method name and in the argument list. Axon must carry WhatsApp and SMS for tenants, sent
under the TENANT's own WABA, DLT registration and credentials. So the port takes a
``Message`` carrying its channel, and an adapter declares which channel it serves.

WHAT THE WIDENING IS NOT. It is not an attempt to model WhatsApp or SMS today. Both need an
approved template, a registered sender identity and a per-tenant credential, and none of the
three is readable from this repository: the regulatory processes are outside it. Adding
speculative fields for them would be inventing a contract. The port carries what an email
send actually needs and a channel that says which adapter should get it; the shapes those
other channels require arrive with the adapters that need them.

ONE ADAPTER PER PROVIDER, SELECTED BY CHANNEL. Provider choice is per-tenant configuration
in the destination design, so nothing here may bind a provider to a channel globally. The
registry below maps a channel to the adapter configured for it in THIS process, which for
Sevyn8's own platform traffic is exactly one entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Channel(StrEnum):
    """The channels the ledger's CHECK constraints know about.

    EMAIL is the only one an adapter exists for. WHATSAPP and SMS are declared because the
    tenant ledger's ``ck_tenant_deliveries_channel_vocab`` names them and a Python vocabulary
    narrower than the database's would make a legal row unrepresentable in the code that
    writes it. Same reasoning as ``synapse.core.provision.Rung`` declaring SUGGEST while
    nothing implements it: naming the next member is what makes a guard testable today.

    A message on a channel with no registered adapter fails at the registry with a message
    naming the legal set, not at the provider and not silently.
    """

    EMAIL = "email"
    WHATSAPP = "whatsapp"
    SMS = "sms"


@dataclass(frozen=True)
class Message:
    """One message, addressed and rendered, ready for a provider.

    RENDERED ALREADY. The port does not template: what reaches an adapter is the final text.
    For a tenant channel that text will have been produced from an approved template and the
    delivery row will pin the template version that produced it, because a message that
    cannot say which template rendered it is unreconstructable. That rendering step does not
    exist yet and this contract does not pretend otherwise.

    ``subject`` IS EMAIL-SHAPED AND OPTIONAL FOR THAT REASON. WhatsApp and SMS have no
    subject line. It is typed as optional rather than removed so the email adapter can
    require it at its own boundary, where the requirement is real.
    """

    channel: Channel
    recipient: str
    body: str
    subject: str | None = None


@runtime_checkable
class ChannelAdapter(Protocol):
    """What one provider, on one channel, can do.

    ``runtime_checkable`` so a test can assert a fake satisfies it, which is the seam CM's
    ``EmailSender`` established and the reason its suite never touches real SendGrid.
    """

    @property
    def channel(self) -> Channel:
        """The channel this adapter serves."""
        ...

    @property
    def provider(self) -> str:
        """The provider name recorded on the ledger row, e.g. ``sendgrid``."""
        ...

    async def send(self, message: Message) -> None:
        """Hand the message to the provider.

        Returns on ACCEPTANCE, raises ``ChannelSendError`` otherwise. Acceptance is not
        delivery: see the ledger's state vocabulary. Nothing an adapter can observe at send
        time tells it whether the message arrived.
        """
        ...
