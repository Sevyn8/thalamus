"""The ledger write. One INSERT, one table, one credential.

THE WHOLE DATABASE SURFACE OF THIS MODULE IS THE STATEMENT BELOW. It is written out rather than
built so a reader sees all of it at once, which is the shape synapse's lifecycle.py and
provision.py both take for the same reason.

WHAT KEEPS IT NARROW, and only the last is code:

  1. THE CREDENTIAL. ``axon_sender`` holds INSERT on ``axon.platform_deliveries`` and nothing
     else. No SELECT anywhere, no UPDATE, no DELETE, nothing at all on ``axon.tenant_deliveries``.
     This module could contain any statement and Postgres would refuse it.
  2. THE VOCABULARIES. State and suppression reason are Python enums mirroring the CHECK
     constraints, so a bad value is refused at the boundary naming the legal set rather than as
     an opaque constraint violation after the send already happened.
  3. NO READS. See below.

=================================================================================================
ZERO DATABASE READS, AND THAT IS WHY THE GRANT HOLDS NO SELECT
=================================================================================================
Every input arrives from the caller or from configuration:

    the recipient      configuration (an env var), not a row
    the credential     an env-mounted secret, not a row
    the delivery id    minted by the caller with new_uuid7
    the subject pair   passed by the producer
    the outcome        what the adapter just did

So the statement below has no RETURNING and no ON CONFLICT, and neither is an accident.

RETURNING NEEDS SELECT. A server-generated ``DEFAULT uuidv7()`` would leave the writer unable to
learn the id it wrote without a privilege the role must not hold. The caller mints the id instead
(uuid4 is banned project-wide; ``synapse.action_events.lifecycle_event_id`` takes the same
discipline for the same reason).

=================================================================================================
ON CONFLICT WOULD FAIL HERE EXACTLY AS IT FAILED IN SLICE 5e. READ THIS BEFORE ADDING IT.
=================================================================================================
There is NO IDEMPOTENCY MECHANISM in this slice, deliberately, because there is nothing to be
idempotent against: the call is in-process and synchronous, once per producer event. A second
operator action is a second delivery and a second row, which is correct.

THE QUEUE CHANGES THAT. Pub/Sub redelivers, so the same message can arrive twice and the obvious
mechanism is a natural key plus ``ON CONFLICT ... DO NOTHING``. IT WILL FAIL. ON CONFLICT has to
READ the arbiter index to detect the conflict, that read needs SELECT, and this role holds none.
Slice 5e shipped exactly that and every enable in production failed with
``permission denied for table provision`` from deploy until it was found.

THE TWO AVAILABLE ANSWERS, so the next person does not have to rediscover them:

  1. CATCH THE UNIQUE VIOLATION. Add a unique constraint, let the INSERT raise SQLSTATE 23505,
     and match on the SQLSTATE together with the CONSTRAINT NAME (never on message text, and
     never on the SQLSTATE alone: 23505 is raised by every unique constraint in the database and
     a broad except turns an unrelated integrity failure into a silent success). This is what 5e
     was fixed to do.
  2. DEDUPLICATE BEFORE THE WRITE, in the consumer, on a producer-supplied key. Costs no grant
     at all and is the cheaper option if the queue already carries a stable message id.

Whichever is chosen, choose it WITH its grant, in the same slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from axon.errors import LedgerWriteError
from dis_rls import rls_platform_session

__all__ = [
    "DeliveryRecord",
    "DeliveryState",
    "SuppressionReason",
    "record_platform_delivery",
]


class DeliveryState(StrEnum):
    """What became of a delivery. Mirrors ck_platform_deliveries_state_vocab.

    ACCEPTED IS NOT SENT AND IS NOT DELIVERED. It means the provider took the message. Whether
    it arrived is knowable only from an inbound receipt, and nothing in this platform receives
    one yet. The name is the guard: a state called ``sent`` would make every future reader of
    this ledger believe something it cannot support.

    THERE IS NO ``queued``. Nothing can produce it: the row is written after the provider answers
    because there is no queue. It arrives with the queue, and it arrives together with the UPDATE
    grant that moving a row between states requires.
    """

    ACCEPTED = "accepted"
    FAILED = "failed"
    SUPPRESSED = "suppressed"


class SuppressionReason(StrEnum):
    """Why a message was deliberately not sent. Mirrors ck_platform_deliveries_suppression_vocab.

    NONE OF THESE CAN OCCUR IN THIS SLICE, and they are declared anyway. Platform email has an
    address from configuration, a credential of Sevyn8's own, no consent gate (internal on-call
    is not a data subject being marketed to) and no template. All four become reachable for
    TENANT traffic, where the tenant is the sender and any of them can be the honest answer.

    They exist now so the CHECK constraint that names them does not have to be altered on a
    populated table the day the address book lands. A vocabulary is cheap to declare and
    expensive to widen once rows depend on it.
    """

    NO_ADDRESS = "no_address"
    CHANNEL_NOT_ONBOARDED = "channel_not_onboarded"
    CONSENT_WITHHELD = "consent_withheld"
    NO_APPROVED_TEMPLATE = "no_approved_template"


@dataclass(frozen=True)
class DeliveryRecord:
    """One row of the platform ledger, assembled by the caller.

    FROZEN, and every field required with no defaults except the three that are genuinely
    optional at the database. A record assembled by keyword cannot silently omit the state.
    """

    delivery_id: UUID
    created_at: datetime
    channel: str
    notification_class: str
    subject_kind: str
    subject_id: str
    recipient: str
    state: DeliveryState
    provider: str
    suppression_reason: SuppressionReason | None = None
    failure_detail: str | None = None
    actor_subject: str | None = None


# THE ONE STATEMENT. No RETURNING, no ON CONFLICT: see the module docstring for both.
#
# template_version_id IS ABSENT FROM THE COLUMN LIST, not passed as NULL. The platform table
# CHECK-forces it NULL, so naming it here would be writing a value the constraint exists to
# refuse. The column is on the table only to keep one column list across the audience pair.
_INSERT_PLATFORM = text(
    """
    INSERT INTO axon.platform_deliveries (
        delivery_id, created_at, channel, notification_class,
        subject_kind, subject_id, recipient,
        state, suppression_reason, provider, failure_detail, actor_subject
    ) VALUES (
        CAST(:delivery_id AS uuid), :created_at, :channel, :notification_class,
        :subject_kind, :subject_id, :recipient,
        :state, :suppression_reason, :provider, :failure_detail, :actor_subject
    )
    """
)


async def record_platform_delivery(engine: AsyncEngine, record: DeliveryRecord) -> None:
    """Append one row to the platform ledger.

    SESSION POSTURE, STATED BECAUSE EVERY QUERY AGAINST THIS ESTATE MUST STATE ONE.
    ``rls_platform_session`` with no acted-for tenant. Two things follow and both are
    deliberate:

      - ``axon.platform_deliveries`` has NO row level security, so no policy is consulted and
        the GUCs this helper sets are inert for this statement. The helper is used anyway
        because it carries dis-rls's FIRST-USE POSTURE GUARD: it verifies on the first use of
        the engine that this is the expected database and that the role is NOSUPERUSER
        NOBYPASSRLS. A sender connecting as a bypassing role would silently defeat the tenant
        ledger's isolation the day it starts writing one, and this is where that is caught.
      - It is NOT the helper the tenant ledger will need. That table's policy pins a write to
        the session's tenant, so the first tenant send opens ``rls_session(engine, tenant_id)``.
        A platform session there would be REFUSED, which is the intended behaviour and is why
        the two paths cannot share one helper.

    Raises ``LedgerWriteError`` on any database failure. The caller decides what that means; see
    ``send.py``, which is the only caller and which cannot let it reach a producer.
    """
    try:
        async with rls_platform_session(engine) as conn:
            await conn.execute(
                _INSERT_PLATFORM,
                {
                    "delivery_id": str(record.delivery_id),
                    "created_at": record.created_at,
                    "channel": record.channel,
                    "notification_class": record.notification_class,
                    "subject_kind": record.subject_kind,
                    "subject_id": record.subject_id,
                    "recipient": record.recipient,
                    "state": str(record.state),
                    "suppression_reason": (
                        str(record.suppression_reason) if record.suppression_reason else None
                    ),
                    "provider": record.provider,
                    "failure_detail": record.failure_detail,
                    "actor_subject": record.actor_subject,
                },
            )
    except DBAPIError as exc:
        # WRAPPED, not re-raised bare. The caller must be able to tell a ledger failure from a
        # send failure without inspecting a driver exception, because the two have different
        # consequences and only one of them leaves evidence behind.
        raise LedgerWriteError(f"the delivery ledger write failed for {record.delivery_id}") from exc
