"""The slot: which scheduled occurrence a run belongs to.

PURE, AND DELIBERATELY FREE OF SYNAPSE TYPES. Nothing here imports an analysis, a declaration,
a capability or a registry. The inputs are a cadence, an IANA timezone and an instant; the
output is the slot that instant falls in. That is the one half of orchestration a future
non-Synapse consumer could reuse unchanged, and keeping it uncontaminated costs nothing.

WHY THIS FUNCTION EXISTS AT ALL, rather than the scheduled time arriving as a parameter — this
is the whole reason, and it is not obvious:

    Cloud Scheduler sets ``X-CloudScheduler-ScheduleTime`` ONLY ON HTTP TARGETS. Scheduling a
    Cloud Run JOB works differently: the scheduler calls the Run Admin API
    (``.../jobs/{job}:run``), and the API launches the container. The container is not an HTTP
    handler, receives no request and therefore no headers, and a job's ``--args`` are static
    configuration that cannot interpolate a date. **There is no way for the intended time to
    reach the process from outside.** So the floor has to happen in here, from the process's own
    clock, and the cadence is what makes that floor stable across a retry.

AND THE RETRY IS NOT HYPOTHETICAL. Setting ``max_retries = 0`` on the Cloud Run job does not
make retries go away: CLOUD SCHEDULER RETRIES THE API CALL ITSELF, so a second execution can be
launched no matter what the job's own retry policy says. Slot stability is therefore
load-bearing rather than defensive — it is the only thing standing between a redelivered
dispatch and a second run. See ``synapse.core.provision`` for what is keyed on it.

THE RESIDUAL, stated rather than hidden: two executions that straddle local midnight floor to
DIFFERENT slots and are two runs. A scheduler retry happens within minutes, so this only bites a
dispatch scheduled within minutes of midnight. The mitigation is not to schedule there, which is
a deployment choice rather than something this function can enforce.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class Cadence(StrEnum):
    """How often a provisioned analysis is due.

    ONE MEMBER, and the honesty is the point — the same posture as ``Verb.REVIEW`` and
    ``GateKind.MIN_HISTORY_DAYS``. Daily is the only cadence anything has ever asked for, and a
    set of speculative alternatives would be a vocabulary invented from zero examples.

    A SUB-DAILY CADENCE CHANGES ``slot_for``'s RETURN TYPE, from ``date`` to something carrying a
    time. That is deliberate: the second cadence should force the shape, rather than this module
    guessing a general ``Slot`` object now and being wrong about it in a way that is expensive to
    unpick — ``as_of`` is a DATE inside an append-only idempotency index, so the current return
    type is not arbitrary, it matches the column the slot feeds.
    """

    DAILY = "daily"


def slot_for(cadence: Cadence, timezone: str, instant: datetime) -> date:
    """The slot ``instant`` falls in, for a thing scheduled at ``cadence`` in ``timezone``.

    TENANT-LOCAL, NOT UTC, and this is the load-bearing decision. The returned date becomes the
    action's ``as_of``, which sits inside ``uq_actions_idempotency`` on an append-only table —
    so its definition cannot be revised once real rows exist without re-keying a log that by
    construction cannot be re-keyed. A UTC day boundary is already known to be wrong for the
    first tenant: an IST sale before 05:30 local falls on the previous UTC date, which is a
    recorded property of this data rather than a hypothetical.

    ``instant`` MUST be timezone-aware. A naive datetime is rejected rather than assumed to be
    UTC: the assumption is invisible when it is right and silently shifts every slot by hours
    when it is wrong, and callers get their instant from ``datetime.now(UTC)`` or a test, both of
    which can supply an aware value trivially.
    """
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError(
            f"slot_for needs a timezone-aware instant, got naive {instant!r}. Guessing UTC here "
            "would silently shift every slot by the tenant's offset"
        )
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(
            f"{timezone!r} is not a resolvable IANA timezone. The slot, and therefore every "
            "action's as_of, is computed in this zone"
        ) from exc

    local = instant.astimezone(zone)
    match cadence:
        case Cadence.DAILY:
            return local.date()
