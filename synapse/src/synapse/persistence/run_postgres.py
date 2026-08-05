"""The run state machine: claim a slot, complete it, or find it already done.

WHAT MAKES A REDELIVERED DISPATCH THE SAME RUN. ``uq_run_slot`` on
``(tenant_id, analysis_id, slot)`` plus ``INSERT ... ON CONFLICT DO NOTHING``. The slot is
derived in-process by ``synapse.core.slot.slot_for`` because it CANNOT arrive from outside: a
Cloud Run job is launched through the Run Admin API and receives no request, so
``X-CloudScheduler-ScheduleTime`` — an HTTP-target header — never reaches it, and static
``--args`` cannot carry a date.

AND THE RETRY IS NOT AVOIDABLE BY CONFIGURATION. ``max_retries = 0`` on the job does not stop
it: Cloud Scheduler retries its OWN API call, so a second execution can be launched whatever the
job's retry policy says. That is why the slot key is load-bearing rather than defensive.

THREE OUTCOMES WHEN A SLOT IS DISPATCHED TWICE, and the middle one is the one worth building:

  1. The row did not exist    -> claimed fresh. Run it.
  2. The row exists UNFINISHED -> a previous attempt died mid-run. TAKE IT OVER and finish it.
     Skipping would leave a partially-appended slot incomplete forever; re-running is safe
     because ``uq_actions_idempotency`` absorbs everything already written. This is the case a
     plain "insert or skip" gets wrong, and it is exactly the case a crash produces.
  3. The row exists FINISHED   -> skip. The work is done and the actions are in the log.

CONCURRENCY IS BOUNDED, NOT SOLVED, and the limit is stated rather than implied. The unique
constraint guarantees ONE ROW PER SLOT under any interleaving. It does not stop two processes
that both observe an unfinished row from both taking it over and running simultaneously. That is
harmless where it matters — identical actions are suppressed by the actions index, so no
duplicate action can result — and visible where it is not: the run row's counts reflect
whichever process completed last. Serialising it properly means a lock held for the run's whole
duration, which a per-statement transaction cannot provide and a long analysis should not hold.
With one scheduler and one job, the window is a crashed attempt overlapping its own retry.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_rls import rls_session
from synapse.core.provision import Provision

__all__ = ["Claim", "PostgresRunRecorder", "RunOutcome"]


# The terminal vocabulary, mirroring ck_run_outcome. Not a StrEnum in synapse.core because it
# describes an ORCHESTRATION result rather than an analytical one, and core is where the
# analytical vocabulary lives; a module-level tuple keeps the two from drifting without adding a
# type to the wrong layer.
RunOutcome = str
OUTCOMES: Sequence[RunOutcome] = ("satisfied", "blocked", "undeclared", "failed")


_CLAIM = text(
    """
    INSERT INTO synapse.run (
        run_id, tenant_id, analysis_id, slot,
        cadence, rung, timezone, started_at
    ) VALUES (
        :run_id, :tenant_id, :analysis_id, :slot,
        :cadence, :rung, :timezone, :started_at
    )
    ON CONFLICT ON CONSTRAINT uq_run_slot DO NOTHING
    RETURNING run_id
    """
)

# Read back the row that won the conflict. Deliberately selects `outcome` rather than
# `finished_at`: ck_run_finished_iff_outcome makes them equivalent, and the outcome is the field
# whose NULL actually MEANS "unfinished" rather than merely correlating with it.
_EXISTING = text(
    """
    SELECT run_id, outcome
      FROM synapse.run
     WHERE tenant_id = :tenant_id
       AND analysis_id = :analysis_id
       AND slot = :slot
    """
)

# Completion never touches started_at: that instant belongs to the FIRST attempt at this slot,
# and a takeover overwriting it would erase how long the slot had been stuck.
_COMPLETE = text(
    """
    UPDATE synapse.run
       SET finished_at = :finished_at,
           outcome = :outcome,
           actions_proposed = :actions_proposed,
           actions_appended = :actions_appended,
           detail = :detail
     WHERE run_id = :run_id
    """
)


@dataclass(frozen=True)
class Claim:
    """A slot this process is now responsible for finishing.

    ``taken_over`` distinguishes a fresh claim from the adoption of a crashed attempt. It
    changes nothing about how the run executes — that is the point, the work is idempotent — but
    it is worth surfacing in a log line, because a takeover is the only visible evidence that a
    previous execution died.
    """

    run_id: UUID
    taken_over: bool


class PostgresRunRecorder:
    """Claims and completes rows in ``synapse.run`` for ONE tenant.

    TENANT SCOPE, not PLATFORM, and the policy is what forces it: ``WITH CHECK`` pins writes to
    the acted-for tenant, so the enumerating PLATFORM session (which sets the tenant GUC to
    ``''``) can read every run and write none. The orchestrator therefore enumerates under
    PLATFORM and claims under TENANT — two scopes, one process, each doing what it is allowed to.
    """

    def __init__(self, engine: AsyncEngine, tenant_id: UUID) -> None:
        self._engine = engine
        self._tenant_id = tenant_id

    async def claim(
        self,
        *,
        run_id: UUID,
        provision: Provision,
        slot: date,
        started_at: datetime,
    ) -> Claim | None:
        """Claim ``slot``. ``None`` means it is already finished and there is nothing to do.

        ``run_id`` is supplied rather than minted here for the same reason ``ActionEvent``'s is:
        ``uuid4`` is banned project-wide and ``dis_core``'s UUIDv7 belongs to the layer that is
        allowed to read a clock. A caller that has to pass one cannot accidentally mint a second
        id for a retry of the same slot.

        The cadence, rung and timezone are SNAPSHOTTED onto the row here. The provision is
        mutable; what was in force for this run must not change when an operator edits it next
        month.
        """
        parameters = {
            "run_id": str(run_id),
            "tenant_id": str(self._tenant_id),
            "analysis_id": provision.analysis_id,
            "slot": slot,
            "cadence": provision.cadence.value,
            "rung": provision.rung.value,
            "timezone": provision.timezone,
            "started_at": started_at,
        }
        lookup = {
            "tenant_id": str(self._tenant_id),
            "analysis_id": provision.analysis_id,
            "slot": slot,
        }
        async with rls_session(self._engine, self._tenant_id) as conn:
            claimed = (await conn.execute(_CLAIM, parameters)).scalar_one_or_none()
            if claimed is not None:
                return Claim(run_id=run_id, taken_over=False)

            existing = (await conn.execute(_EXISTING, lookup)).mappings().one()

        if existing["outcome"] is not None:
            return None
        return Claim(
            run_id=existing["run_id"]
            if isinstance(existing["run_id"], UUID)
            else UUID(str(existing["run_id"])),
            taken_over=True,
        )

    async def complete(
        self,
        *,
        run_id: UUID,
        finished_at: datetime,
        outcome: RunOutcome,
        actions_proposed: int | None = None,
        actions_appended: int | None = None,
        detail: str | None = None,
    ) -> None:
        """Mark a claimed run terminal. Refuses an outcome the CHECK constraint would reject.

        Checked here as well as in the database because the database's refusal arrives as an
        opaque constraint violation at the end of a run that has already appended its actions,
        where this one names the bad value at the call site.
        """
        if outcome not in OUTCOMES:
            raise ValueError(
                f"{outcome!r} is not a run outcome; expected one of {sorted(OUTCOMES)}. "
                "ck_run_outcome would refuse this after the run's actions had already landed"
            )
        async with rls_session(self._engine, self._tenant_id) as conn:
            await conn.execute(
                _COMPLETE,
                {
                    "run_id": str(run_id),
                    "finished_at": finished_at,
                    "outcome": outcome,
                    "actions_proposed": actions_proposed,
                    "actions_appended": actions_appended,
                    "detail": detail,
                },
            )
