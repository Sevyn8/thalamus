"""The ONLY write path in this service. One INSERT, one table, one credential.

THIS MODULE IS THE WHOLE CONTRACT CHANGE. Everything else here reads; this appends operator
decisions to ``synapse.action_events``. It is a separate module rather than a function in
``reads.py`` so that "where can this service write" has a one-file answer, and so the
no-write test can name the exception precisely instead of being weakened into a general
permission.

FOUR THINGS KEEP IT NARROW, and only the last is code:

  1. THE CREDENTIAL. ``synapse_lifecycle`` holds INSERT on ``synapse.action_events`` and
     nothing else — no SELECT, no UPDATE, no DELETE, no other table (migration 0006). This
     module could contain any statement at all and Postgres would still refuse it.
  2. THE TRIGGER. The table is append-only and binds even the owner, so a decision cannot be
     edited into something else after the fact.
  3. THE POLICY. FORCE ROW LEVEL SECURITY with ``WITH CHECK (tenant_id = app.tenant_id)``, so
     the write opens a TENANT-scoped session for the alert's own tenant. A PLATFORM session
     (tenant GUC '') can read every event and write none — which is why the read path and the
     write path cannot share one session helper here.
  4. THE VOCABULARIES. Verb and reason are Python enums mirroring the CHECK constraints, so a
     bad value is refused at the boundary with a message naming the legal set, rather than as
     an opaque constraint violation after the request has been accepted.

THE TARGET GRAIN IS COPIED FROM THE ALERT, NOT DERIVED HERE. A snooze means "this product at
this store", so the event records ``(declaration_id, target)`` — the same key the actions
idempotency index uses. The caller reads those off the alert through the READER credential
first; this module cannot read them, by design.

IT NEVER SUPPRESSES A DETECTION. Nothing in the orchestrator reads this table. A snooze hides
rows at READ time and the sweep keeps recording, so when the snooze lapses the full history is
there — including everything detected while it was quiet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_core.ids import new_uuid7
from dis_rls import rls_session

__all__ = [
    "DismissReason",
    "LifecycleVerb",
    "LifecycleWriteError",
    "record_decision",
]


class LifecycleVerb(StrEnum):
    """What an operator did. Mirrors ck_action_events_verb.

    ACKNOWLEDGE IS NOT A CLOSE. It records that somebody has seen the alert and left it
    standing — the difference between an unread queue and a handled one — and it does not hide
    the alert from any list. Only dismiss and an unexpired snooze do that.
    """

    SNOOZE = "snooze"
    DISMISS = "dismiss"
    ACKNOWLEDGE = "acknowledge"


class DismissReason(StrEnum):
    """Why an alert was dismissed. Mirrors ck_action_events_reason.

    THESE ARE TRAINING LABELS, not UI copy. Each one is a statement about why the detection was
    not useful, and the whole point of a closed set is that somebody can GROUP BY it in a year
    and ask which monitor produces which kind of false positive. Free text cannot be counted,
    which is why there is no note field.
    """

    SEASONAL = "seasonal"
    DISPLAY_STOCK = "display_stock"
    DISCONTINUED = "discontinued"
    WRONG_DATA = "wrong_data"


class LifecycleWriteError(ValueError):
    """A decision this module refuses to store. Raised BEFORE any connection is opened."""


# The one statement this service can execute that is not a SELECT. Written out rather than
# built, so a reader of this file sees the entire write surface at once.
_INSERT = text(
    """
    INSERT INTO synapse.action_events (
        lifecycle_event_id, action_event_id, tenant_id,
        declaration_id, target, verb, reason, snoozed_until,
        actor_subject, recorded_at
    ) VALUES (
        :lifecycle_event_id, CAST(:action_event_id AS uuid), CAST(:tenant_id AS uuid),
        :declaration_id, CAST(:target AS jsonb), :verb, :reason, :snoozed_until,
        :actor_subject, :recorded_at
    )
    """
)


@dataclass(frozen=True)
class Decision:
    """One operator decision, validated. Constructing it is what refuses a bad combination."""

    action_event_id: UUID
    tenant_id: UUID
    declaration_id: str
    target: Any
    verb: LifecycleVerb
    reason: DismissReason | None
    snoozed_until: date | None
    actor_subject: str

    def __post_init__(self) -> None:
        # THE SAME PAIRINGS THE CHECK CONSTRAINTS ENFORCE, asserted here so the caller gets a
        # message naming the legal set instead of a constraint violation after the request was
        # accepted. Both are kept: this one explains, the constraint guarantees.
        if self.verb is LifecycleVerb.DISMISS and self.reason is None:
            raise LifecycleWriteError(
                "a dismissal must carry a reason — one of "
                f"{sorted(r.value for r in DismissReason)}. An unlabelled dismissal is an "
                "unlabelled negative example, which is the reason the set exists"
            )
        if self.verb is not LifecycleVerb.DISMISS and self.reason is not None:
            raise LifecycleWriteError(f"{self.verb.value!r} takes no reason; only a dismissal does")
        if self.verb is LifecycleVerb.SNOOZE and self.snoozed_until is None:
            raise LifecycleWriteError(
                "a snooze must carry an expiry date. A snooze with no expiry is a dismissal "
                "wearing the wrong verb, and it would never resurface"
            )
        if self.verb is not LifecycleVerb.SNOOZE and self.snoozed_until is not None:
            raise LifecycleWriteError(f"{self.verb.value!r} takes no expiry date; only a snooze does")


async def record_decision(
    engine: AsyncEngine,
    decision: Decision,
    *,
    recorded_at: datetime,
) -> UUID:
    """Append one lifecycle event. Returns its id.

    ``rls_session``, NOT ``rls_platform_session``, and that is forced rather than chosen: the
    policy's ``WITH CHECK`` compares ``app.tenant_id``, so a PLATFORM session — which sets the
    tenant GUC to '' — matches no row and the insert is refused. PLATFORM widens reads only.
    This is the one place in the service where a tenant-scoped session is correct.

    ``recorded_at`` IS INJECTED, never read from a clock here. The column records what the
    caller observed; a default would substitute the database's clock, and a function that reads
    the clock cannot be tested at a boundary.
    """
    import json

    lifecycle_event_id = new_uuid7()
    async with rls_session(engine, decision.tenant_id) as conn:
        await conn.execute(
            _INSERT,
            {
                "lifecycle_event_id": str(lifecycle_event_id),
                "action_event_id": str(decision.action_event_id),
                "tenant_id": str(decision.tenant_id),
                "declaration_id": decision.declaration_id,
                "target": json.dumps(decision.target, sort_keys=True),
                "verb": decision.verb.value,
                "reason": decision.reason.value if decision.reason else None,
                "snoozed_until": decision.snoozed_until,
                "actor_subject": decision.actor_subject,
                "recorded_at": recorded_at,
            },
        )
    return lifecycle_event_id
