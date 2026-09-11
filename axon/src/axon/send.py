"""The send path: hand a message to an adapter, then record what happened. In that order.

=================================================================================================
FIRE AND RECORD. A SEND FAILURE MUST NEVER FAIL THE THING THAT CAUSED IT.
=================================================================================================
The producer is an operator action that has ALREADY COMMITTED by the time this is called. An
operator enabled a monitor; the row is in the database; the request is going to answer 200. That
an email did not go out is worth knowing and is not worth undoing an enable for.

So ``send_platform`` raises NOTHING. A provider refusal is recorded as ``failed`` with the
detail and returned as an outcome the caller may log. There is no path from a bad SendGrid
response to a failed enable.

FIRE AND RECORD IS NOT FIRE AND FORGET, and the difference is the ledger. A swallowed failure
that left no row would be the same as no delivery plane at all: nobody would know the mail did
not go, and the absence would be indistinguishable from nobody having tried.

=================================================================================================
THE QUEUE IS IN FRONT OF THIS, AND WHAT IT DOES AND DOES NOT CLOSE
=================================================================================================
A durable queue sits in front of this path. The intent is persisted at publish time, so a
consumer that dies mid-send leaves a message that is REDELIVERED rather than an intent that
evaporated, and a failed ledger write nacks and is retried instead of vanishing. Without the
queue, a failed ledger write would leave no row, possibly an email, and a successful enable.

=================================================================================================
AT-LEAST-ONCE, AND THE RESIDUAL ASYMMETRY
=================================================================================================
THE LEDGER WRITE IS IDEMPOTENT. THE SEND IS NOT.

``delivery_id`` is minted by the PRODUCER and travels in the envelope, so a redelivered message
reaches the same ``pk_platform_deliveries`` and the second INSERT is refused. ``ledger.py``
records why that needed no constraint and no grant.

The provider call has no such key. So there is one window left: A CRASH BETWEEN THE PROVIDER'S
202 AND THE LEDGER COMMIT. On redelivery the ledger holds no row, this path cannot know the
message already went, and it sends again. The result is a duplicate email, bounded by
``max_delivery_attempts`` on the subscription, which is set to 5 for exactly this reason.

NOTHING AVAILABLE CLOSES THAT WINDOW, and the near misses are worth naming so they are not
re-proposed. Reading the ledger before sending does not help: after a failed write there is no
row to find, so the reread and the resend agree on nothing. Writing a `queued` row first and
updating it after does not help either, and costs more: without SELECT the consumer still cannot
learn whether the send happened, so it buys a state nobody can act on while giving up the
property that the ledger cannot be rewritten.

WHAT WOULD CLOSE IT IS A PROVIDER-SIDE IDEMPOTENCY KEY, and WHETHER SENDGRID v3 MAIL SEND
ACCEPTS ONE IS UNVERIFIED. ``sendgrid.py`` sets personalizations, from, subject, content and
tracking settings and nothing else, and no claim is made here beyond that. If the provider does
accept one, passing ``delivery_id`` as that key is a cheap follow-on and would make the send as
idempotent as the write. It is a thing to check, not a design assumption.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from axon.channel import ChannelAdapter, Message
from axon.errors import ChannelSendError, LedgerWriteError
from axon.ledger import DeliveryRecord, DeliveryState, record_platform_delivery

__all__ = ["SendOutcome", "send_platform"]


@dataclass(frozen=True)
class SendOutcome:
    """What happened, for the caller to log. Never raised, always returned.

    ``recorded`` IS SEPARATE FROM ``state`` ON PURPOSE. A send can fail and be recorded (the
    normal failure, and it is fine: there is evidence). A send can succeed and NOT be recorded,
    which is the hole named in the module docstring and the only case where the caller should
    log at ERROR rather than WARNING.
    """

    state: DeliveryState
    recorded: bool
    detail: str | None = None
    # True when the ledger already held this delivery_id, so this attempt wrote nothing. Under a
    # queue that means a redelivery of a message a previous attempt had already recorded. It is
    # SEPARATE FROM `recorded` because both are true at once: the evidence exists (recorded) and
    # this pass did not create it (duplicate). The consumer acks either way and logs differently.
    duplicate: bool = False


async def send_platform(
    *,
    engine: AsyncEngine,
    adapter: ChannelAdapter,
    message: Message,
    delivery_id: UUID,
    notification_class: str,
    subject_kind: str,
    subject_id: str,
    actor_subject: str | None = None,
) -> SendOutcome:
    """Send one platform message and record it. Raises nothing.

    ``delivery_id`` IS SUPPLIED BY THE CALLER AND IS THE IDEMPOTENCY KEY. Minting it here would
    mint a new id per redelivery and the primary key would refuse nothing, so the mint lives with
    the PRODUCER and rides in the envelope. It is a UUIDv7, and it is what lets the row be
    written without RETURNING, which is what lets the sender's grant hold no SELECT.

    THE ORDER IS SEND, THEN RECORD, and it is forced rather than chosen. The row states an
    OUTCOME, and the outcome is not known until the provider has answered. Writing first would
    mean writing a state that does not exist in the vocabulary (there is no ``queued`` until
    there is a queue) or writing a lie and correcting it, which needs the UPDATE grant this role
    deliberately does not hold.
    """
    created_at = datetime.now(UTC)

    state = DeliveryState.ACCEPTED
    failure_detail: str | None = None

    try:
        await adapter.send(message)
    except ChannelSendError as exc:
        # RECORDED, NOT RAISED. The producer already committed; see the module docstring.
        state = DeliveryState.FAILED
        failure_detail = exc.detail

    record = DeliveryRecord(
        delivery_id=delivery_id,
        created_at=created_at,
        channel=str(message.channel),
        notification_class=notification_class,
        subject_kind=subject_kind,
        subject_id=subject_id,
        recipient=message.recipient,
        state=state,
        provider=adapter.provider,
        failure_detail=failure_detail,
        actor_subject=actor_subject,
    )

    try:
        was_new = await record_platform_delivery(engine, record)
    except LedgerWriteError as exc:
        # NO LONGER THE END OF THE STORY, AND THAT IS WHAT THE QUEUE BOUGHT. Everything above may
        # have succeeded and there is no evidence of it yet, but the MESSAGE still exists: the
        # consumer nacks on `recorded=False` and the write is retried. Returned rather than raised
        # so the caller decides; in-process callers (if any remain) still must not let it through.
        return SendOutcome(state=state, recorded=False, detail=str(exc))

    return SendOutcome(state=state, recorded=True, detail=failure_detail, duplicate=not was_new)
