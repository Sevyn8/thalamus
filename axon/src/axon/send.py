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
THE HOLE THIS SLICE CANNOT CLOSE, AND THE REASON THE QUEUE EXISTS
=================================================================================================
There is one outcome this design cannot record: THE LEDGER WRITE ITSELF FAILING.

If the database is unreachable at that moment, then there is no row, there may or may not have
been an email, and the enable succeeded. Nothing afterwards can tell that anything was ever
owed, because the only evidence of the intent was the row that failed to be written. It is not
a small hole: a database blip during a send is precisely when a delivery plane's records matter.

IT IS LOGGED AT ERROR WITH `severity`, WHICH IS THE MOST THIS SLICE CAN DO. Cloud Logging files
anything without `severity` at DEFAULT where no alert can match it, so the field is the whole
point of the line. A log line is not a ledger, and thirty days later it is not even a log line.

THE FIX IS THE QUEUE, AND THIS IS WHAT IT IS FOR. With a durable queue in front of the send, the
intent is persisted BEFORE anything is attempted: the producer's only job is to enqueue, which
either succeeds or fails loudly inside the producer's own request, and a consumer that dies
mid-send leaves a message that is redelivered rather than an intent that evaporated. The ledger
write stops being the first durable record and becomes a state transition on one that already
exists.

If you are reading this because you are building that queue: the redelivery it introduces is
what makes idempotency real, and ``ledger.py``'s docstring records why the obvious mechanism
(ON CONFLICT on a natural key) fails against this role's grant and what the two working answers
are. Decide it there, with its grant, in that slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncEngine

from axon.channel import ChannelAdapter, Message
from axon.errors import ChannelSendError, LedgerWriteError
from axon.ledger import DeliveryRecord, DeliveryState, record_platform_delivery
from dis_core.ids import new_uuid7

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


async def send_platform(
    *,
    engine: AsyncEngine,
    adapter: ChannelAdapter,
    message: Message,
    notification_class: str,
    subject_kind: str,
    subject_id: str,
    actor_subject: str | None = None,
) -> SendOutcome:
    """Send one platform message and record it. Raises nothing.

    THE ID IS MINTED HERE, BEFORE ANYTHING IS ATTEMPTED, and it is a UUIDv7 so it carries the
    instant. That is what lets the row be written without RETURNING, which is what lets the
    sender's grant hold no SELECT. See ledger.py.

    THE ORDER IS SEND, THEN RECORD, and it is forced rather than chosen. The row states an
    OUTCOME, and the outcome is not known until the provider has answered. Writing first would
    mean writing a state that does not exist in the vocabulary (there is no ``queued`` until
    there is a queue) or writing a lie and correcting it, which needs the UPDATE grant this role
    deliberately does not hold.
    """
    delivery_id = new_uuid7()
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
        await record_platform_delivery(engine, record)
    except LedgerWriteError as exc:
        # THE HOLE. Everything above may have succeeded and there is now no evidence of it.
        # Returned rather than raised, with `recorded=False` so the caller can log at ERROR:
        # this is the one case that is worse than a failed send.
        return SendOutcome(state=state, recorded=False, detail=str(exc))

    return SendOutcome(state=state, recorded=True, detail=failure_detail)
