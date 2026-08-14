"""Axon: the platform's communications and delivery plane.

AXON HOLDS ADDRESSES AND SEND STATE. NOTHING ELSE. Auth, RBAC, roles, permissions, logins and
identity are Customer Master's, always. If Axon needs to know who somebody is it asks CM, and a
person with no CM user cannot be addressed by Axon.

WHAT SLICE 1 WAS. One real internal event reaching a real inbox and leaving a ledger row: the
delivery ledger split by audience, the Channel port with one SendGrid adapter, and a send path
that records what happened. Sevyn8's own platform traffic is email only, on Sevyn8's own
credential, and the ledger says so with a CHECK rather than a convention.

WHAT SLICE 3 ADDED. The read side: ``reads.py``, a fleet-wide union across both ledgers under a
session that can read everything and write nothing, plus the counts that make the one suppression
reason worth acting on visible. It landed BEFORE the queue on purpose: slice 2 makes sending
asynchronous and adds a dead-letter lane, and debugging that through psql is worse than debugging
it with a screen.

WHAT SLICE 4 ADDED, AND IT IS RAILS RATHER THAN TRAFFIC. Two tenant-scoped tables,
``axon.channel_connections`` and ``axon.channel_templates``, plus ``vault.secret_id_for``, plus
the composite foreign key that lets a tenant delivery pin the template version that rendered
it. NOTHING READS OR WRITES ANY OF IT YET: both tables ship empty and ungranted on slice 1's
recorded precedent, and the naming function is an accepted zero-dead-controls exception whose
docstring says why.

WHAT IS STILL NOT HERE, and none of these is an oversight: no address book, no tenant channel
surface, no credential collection, no inbound webhooks, no adapter beyond SendGrid, and no
template row anywhere. The registry stays empty until an adapter can verify a send, because a
seeded name that turns out to be wrong is worse than an empty table: an empty table suppresses
with a reason and a wrong name fails at the provider. Each remaining piece is its own slice and
each is named where the code that will need it lives.

THE DESTINATION IS TENANT-FACING MULTI-CHANNEL DELIVERY, and nothing here may make that a
rewrite. The tenant, not Sevyn8, is the sender for tenant traffic: its own WhatsApp Business
account, its own DLT registration and approved templates, its own credentials, and consent that
is consent to be contacted by THAT tenant. So the ledger is a pair rather than one table with a
flag, the port takes a channel rather than assuming email, the subject is an opaque (kind, id)
pair rather than a foreign key, and the state vocabulary already carries the suppression reasons
an unonboarded channel will need.
"""

from axon.channel import Channel, ChannelAdapter, Message
from axon.envelope import TOPIC_SEND_REQUESTED, Publisher, SendRequested
from axon.errors import AxonError, ChannelSendError, LedgerWriteError
from axon.ledger import DeliveryRecord, DeliveryState, SuppressionReason, record_platform_delivery
from axon.reads import DeliveryCounts, DeliveryRow, delivery_counts, recent_deliveries
from axon.send import SendOutcome, send_platform
from axon.sendgrid import SendGridEmailAdapter
from axon.vault import secret_id_for

__all__ = [
    "AxonError",
    "Channel",
    "ChannelAdapter",
    "ChannelSendError",
    "DeliveryCounts",
    "DeliveryRecord",
    "DeliveryRow",
    "DeliveryState",
    "LedgerWriteError",
    "Message",
    "Publisher",
    "SendGridEmailAdapter",
    "SendRequested",
    "SendOutcome",
    "SuppressionReason",
    "TOPIC_SEND_REQUESTED",
    "delivery_counts",
    "record_platform_delivery",
    "recent_deliveries",
    "secret_id_for",
    "send_platform",
]
