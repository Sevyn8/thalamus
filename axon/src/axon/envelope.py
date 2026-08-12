"""The ``axon.send.requested`` envelope, and the publisher seam.

ONE MESSAGE IS ONE DELIVERY. The producer mints ``delivery_id`` and puts it here, which is the
single change that makes the whole slice idempotent: that id is already
``pk_platform_deliveries``, so a redelivered message reaches the same primary key and the INSERT
refuses it. Nothing else needs a constraint, a dedup table or a grant.

=================================================================================================
WHY THE ID IS MINTED BY THE PRODUCER AND NOT BY THE CONSUMER
=================================================================================================
Slice 1 minted it inside ``send_platform``, which was correct while the call was in-process and
once per producer event. Under a queue it would mint a NEW id on every redelivery, so the same
intent would reach the ledger as N distinct rows and the primary key would refuse none of them.
Moving the mint to the producer is what turns "the same message" into "the same row".

It is a UUIDv7, so it also carries the instant the intent was formed rather than the instant the
provider answered. Those differ by however long the message sat in the queue, and the ledger's
``created_at`` is the send instant, so the two are deliberately not the same clock reading.

=================================================================================================
NO PUBSUB IMPORT IN THIS MODULE, AND THAT IS A DEPENDENCY DECISION RATHER THAN TIDINESS
=================================================================================================
``thalamus-axon`` is imported by synapse-ui-server, which builds a container. If the concrete
publisher lived here, ``google-cloud-pubsub`` would enter the closure of every consumer of this
library whether it publishes or not. So this module holds the envelope and a ``Publisher``
Protocol; the concrete ``PubsubPublisher`` lives in the service that publishes and declares the
dependency itself. That is dis-ui-server's shape (``publisher.py`` there), and the same reason.

THE PROTOCOL IS ALSO THE TEST SEAM. Every test in this repository that exercises a publish drives
a fake satisfying this Protocol, asserted with ``isinstance`` so a Protocol change cannot leave
the fakes passing against a contract nothing implements.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from axon.channel import Channel

__all__ = ["Publisher", "SendRequested", "TOPIC_SEND_REQUESTED"]

# The topic name. Declared here rather than in a service's config because BOTH sides need it and
# a name that lives in two configs is a name that can disagree with itself.
TOPIC_SEND_REQUESTED = "axon-send-requested"

# The envelope's shape version. Present from the first message so that adding a field later is a
# version bump a consumer can branch on, rather than a guess about which producers have deployed.
_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SendRequested:
    """One request to send one message. The whole contract between producer and sender.

    FROZEN AND FULLY REQUIRED except the two fields that are genuinely optional at the ledger.
    An envelope assembled by keyword cannot silently omit the recipient.

    IT CARRIES THE RENDERED SUBJECT AND BODY, not a template id and a parameter bag. There is no
    template registry and this slice does not build one, so the producer renders and the sender
    delivers. When templates land, a ``template_version_id`` joins this shape and the rendering
    moves; that is a version bump, and the field on the ledger already exists for it.

    NO CREDENTIAL AND NO PROVIDER. Sevyn8's own SendGrid key is the sender's configuration, not
    the message's. A tenant send will name a channel whose credential the sender resolves; putting
    a credential on a queue message would put it in a 31 day dead-letter retention.
    """

    delivery_id: UUID
    channel: Channel
    recipient: str
    subject: str
    body: str
    notification_class: str
    subject_kind: str
    subject_id: str
    actor_subject: str | None = None
    schema_version: int = _SCHEMA_VERSION

    def to_json(self) -> bytes:
        """Serialise for the wire. UTF-8 JSON, the same shape ``from_json`` reads."""
        return json.dumps(
            {
                "schema_version": self.schema_version,
                "delivery_id": str(self.delivery_id),
                "channel": str(self.channel),
                "recipient": self.recipient,
                "subject": self.subject,
                "body": self.body,
                "notification_class": self.notification_class,
                "subject_kind": self.subject_kind,
                "subject_id": self.subject_id,
                "actor_subject": self.actor_subject,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    @classmethod
    def from_json(cls, raw: bytes) -> SendRequested:
        """Parse one message body.

        RAISES ON ANYTHING IT CANNOT READ, and the consumer turns that into a nack rather than an
        ack. A malformed envelope is not a message to discard quietly: it is either a producer bug
        or a version skew, and both are worth the dead-letter lane after the attempts run out.

        AN UNKNOWN schema_version IS REFUSED rather than best-effort parsed. A consumer that reads
        a newer envelope by ignoring the fields it does not recognise will send a message that is
        missing whatever the new field was for, which is worse than not sending it.
        """
        payload: Any = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"envelope is {type(payload).__name__}, not an object")
        version = payload.get("schema_version")
        if version != _SCHEMA_VERSION:
            raise ValueError(
                f"envelope schema_version is {version!r}, this consumer reads {_SCHEMA_VERSION}. "
                "A newer envelope is refused rather than partially read: the fields this build "
                "does not know about are the ones a partial read would silently drop"
            )
        return cls(
            delivery_id=UUID(payload["delivery_id"]),
            channel=Channel(payload["channel"]),
            recipient=payload["recipient"],
            subject=payload["subject"],
            body=payload["body"],
            notification_class=payload["notification_class"],
            subject_kind=payload["subject_kind"],
            subject_id=payload["subject_id"],
            actor_subject=payload.get("actor_subject"),
        )


@runtime_checkable
class Publisher(Protocol):
    """Publish ``data`` to ``topic_name``; return the provider's message id.

    Narrow on purpose: one method, bytes in, id out. The producer holds this type, never a
    Pub/Sub client, so a test drives a list and a runtime drives gRPC through the same call site.
    """

    def publish(self, topic_name: str, data: bytes) -> str: ...
