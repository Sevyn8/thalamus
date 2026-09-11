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
ON CONFLICT WOULD FAIL HERE. READ THIS BEFORE ADDING IT.
=================================================================================================
Pub/Sub redelivers, so the same message can arrive twice, and the obvious idempotency mechanism
is a natural key plus ``ON CONFLICT ... DO NOTHING``. IT WILL FAIL. ON CONFLICT has to READ the
arbiter index to detect the conflict, that read needs SELECT, and this role holds none: the
statement fails with ``permission denied`` at runtime, not at deploy.

THE MECHANISM USED INSTEAD NEEDS NO CONSTRAINT AND NO GRANT: CATCH THE UNIQUE VIOLATION. The
INSERT raises SQLSTATE 23505 and is matched on the SQLSTATE together with the CONSTRAINT NAME
(never on message text, and never on the SQLSTATE alone: 23505 is raised by every unique
constraint in the database and a broad except turns an unrelated integrity failure into a silent
success).

WHAT MAKES THAT FREE. The natural key is already the primary key. ``pk_platform_deliveries`` is
on ``delivery_id``, and the PRODUCER mints that id and puts it in the queue envelope. A
redelivered message therefore carries the same id and reaches the same primary key, so a
constraint that already exists is the idempotency mechanism. Catching a violation is server side;
only ON CONFLICT needs to READ the arbiter index, so the write stays possible from a role holding
no SELECT on the table it writes.

WHY NOT DEDUPLICATE BEFORE THE WRITE in the consumer instead: that needs somewhere to remember
what has been seen. Pub/Sub's ``message_id`` is stable across redeliveries of one publish but a
PUBLISHER RETRY mints a new one, so it does not deduplicate the case that matters; and a dedup
table is a table plus a grant plus a retention question.

WHAT THIS DOES NOT MAKE IDEMPOTENT, stated here because the asymmetry matters: THE LEDGER WRITE
IS IDEMPOTENT, THE SEND IS NOT. See ``send.py``.
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

    THERE IS NO ``queued``. Nothing can produce it: the row states an OUTCOME and is written
    after the provider answers. The queue in front of the send path persists the message, not a
    ledger row. A ``queued`` state arrives together with the UPDATE grant that moving a row
    between states requires, and this role holds none.
    """

    ACCEPTED = "accepted"
    FAILED = "failed"
    SUPPRESSED = "suppressed"


class SuppressionReason(StrEnum):
    """Why a message was deliberately not sent. Mirrors ck_platform_deliveries_suppression_vocab.

    NONE OF THESE CAN OCCUR ON THE PLATFORM PATH, and they are declared anyway. Platform email has an
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


async def record_platform_delivery(engine: AsyncEngine, record: DeliveryRecord) -> bool:
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

    RETURNS WHETHER THE ROW WAS NEW. ``False`` means this exact ``delivery_id`` was already in the
    ledger, which under a queue means a redelivery of a message a previous attempt already
    recorded. That is a success from the caller's point of view: the evidence exists and the
    message can be acked. See ``_is_duplicate_delivery`` for why the match is narrow.

    Raises ``LedgerWriteError`` on any OTHER database failure. The caller decides what that means;
    see ``send.py``, which is the only caller and which cannot let it reach a producer.
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
        if _is_duplicate_delivery(exc):
            # THE IDEMPOTENCY BRANCH. A previous attempt at this same message already wrote this
            # row, so the ledger is already correct and there is nothing left to do. Reported as
            # a value rather than swallowed, because the caller logs the two cases differently:
            # a first write is routine and a duplicate means a redelivery happened.
            return False
        # WRAPPED, not re-raised bare. The caller must be able to tell a ledger failure from a
        # send failure without inspecting a driver exception, because the two have different
        # consequences and only one of them leaves evidence behind.
        raise LedgerWriteError(f"the delivery ledger write failed for {record.delivery_id}") from exc
    return True


def _is_duplicate_delivery(exc: DBAPIError) -> bool:
    """Is this ``pk_platform_deliveries`` refusing a repeat, or some other integrity failure?

    TWO CONDITIONS, BOTH REQUIRED, AND NEITHER IS MESSAGE TEXT. The SQLSTATE says "unique
    violation" and nothing more: 23505 is raised by EVERY unique constraint and unique index in
    the database, including any this table grows later. The CONSTRAINT NAME says WHICH, and
    Postgres sends it in the error's constraint field for integrity-constraint violations, so
    psycopg exposes it on ``.orig.diag.constraint_name``.

    WHY THE PAIR MATTERS MORE THAN EITHER HALF. A broad except on 23505 alone would turn an
    unrelated integrity failure into "already recorded", which the consumer acks. That is a failed
    write reported as a success, on a queue, where the message is then gone. Matching the name
    alone is not available: nothing else in the DBAPI error identifies the class of failure.

    FALSE IS THE SAFE ANSWER AND IS THE DEFAULT. An error with no ``orig``, no ``diag``, or a
    constraint field Postgres did not populate becomes a LedgerWriteError and therefore a nack.
    A redelivery of a genuinely-duplicate message is cheap; acking a genuinely-failed write is not.

    COPIED FROM synapse_ui_server.provision._is_duplicate_provision, deliberately and with the
    reasoning restated rather than imported. The two modules are in different distributions and
    Axon does not depend on Synapse; a shared helper would be a dependency edge in the wrong
    direction for four lines.

    =============================================================================================
    23503 IS A REACHABLE FAILURE ON THE TENANT LEDGER, AND THIS CLASSIFIER DOES NOT KNOW IT
    =============================================================================================
    A composite FOREIGN KEY on axon.tenant_deliveries (tenant_id, template_version_id)
    references axon.channel_templates. So a tenant delivery naming a template version that does
    not exist, or that belongs to ANOTHER TENANT, fails with SQLSTATE 23503 rather than 23505.

    NOT LIVE TODAY. This function serves record_platform_delivery, which writes the PLATFORM
    ledger, and that table has no foreign key at all: ck_platform_deliveries_no_template forces
    the column NULL and there is no tenant_id to compose a reference from. Nothing writes the
    tenant ledger yet.

    WRITTEN HERE RATHER THAN ONLY IN THE DDL because this is where somebody will look the first
    time it fires. The tenant ledger's writer needs its own classifier, and 23503 must NOT be
    folded into the duplicate branch: a duplicate means the evidence already exists and the
    message can be acked, while a foreign key violation means the row was never written and the
    template reference was wrong. Acking the second one loses the delivery and the reason.
    """
    orig = getattr(exc, "orig", None)
    if getattr(orig, "sqlstate", None) != "23505":
        return False
    return getattr(getattr(orig, "diag", None), "constraint_name", None) == "pk_platform_deliveries"
