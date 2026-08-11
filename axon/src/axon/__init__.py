"""Axon: the platform's communications and delivery plane.

AXON HOLDS ADDRESSES AND SEND STATE. NOTHING ELSE. Auth, RBAC, roles, permissions, logins and
identity are Customer Master's, always. If Axon needs to know who somebody is it asks CM, and a
person with no CM user cannot be addressed by Axon.

WHAT SLICE 1 IS. One real internal event reaching a real inbox and leaving a ledger row: the
delivery ledger split by audience, the Channel port with one SendGrid adapter, and a send path
that records what happened. Sevyn8's own platform traffic is email only, on Sevyn8's own
credential, and the ledger says so with a CHECK rather than a convention.

WHAT IT IS NOT, and none of these is an oversight: no queue, no console, no address book, no
templates, no tenant credentials, no inbound webhooks, no adapter beyond SendGrid. Each is its
own slice and each is named where the code that will need it lives.

THE DESTINATION IS TENANT-FACING MULTI-CHANNEL DELIVERY, and nothing here may make that a
rewrite. The tenant, not Sevyn8, is the sender for tenant traffic: its own WhatsApp Business
account, its own DLT registration and approved templates, its own credentials, and consent that
is consent to be contacted by THAT tenant. So the ledger is a pair rather than one table with a
flag, the port takes a channel rather than assuming email, the subject is an opaque (kind, id)
pair rather than a foreign key, and the state vocabulary already carries the suppression reasons
an unonboarded channel will need.
"""

from axon.channel import Channel, ChannelAdapter, Message
from axon.errors import AxonError, ChannelSendError, LedgerWriteError
from axon.ledger import DeliveryRecord, DeliveryState, SuppressionReason, record_platform_delivery
from axon.send import SendOutcome, send_platform
from axon.sendgrid import SendGridEmailAdapter

__all__ = [
    "AxonError",
    "Channel",
    "ChannelAdapter",
    "ChannelSendError",
    "DeliveryRecord",
    "DeliveryState",
    "LedgerWriteError",
    "Message",
    "SendGridEmailAdapter",
    "SendOutcome",
    "SuppressionReason",
    "record_platform_delivery",
    "send_platform",
]
