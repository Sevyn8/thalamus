"""One sweep: every active provision, each due slot, resolved and recorded.

READ ``synapse.orchestrator``'s docstring first — it covers shadow-only, the worker/dispatcher
distinction, and the two RLS scopes. This module is the loop.

WHAT ONE PAIR COSTS, in order:

    slot      <- slot_for(cadence, timezone, now)          pure, tenant-local
    claim     <- run recorder                              None means already finished
    resolve   <- registry.resolve_declaration              three outcomes, all recorded
    plan      <- registry.plan_for(analysis)               fetch, evaluate, propose
    append    <- action appender, one event per action     suppressed repeats counted honestly
    complete  <- run recorder                              terminal outcome + counts

A FAILURE FOR ONE TENANT DOES NOT ABORT THE SWEEP. It is recorded as an outcome of ``failed``
with the exception text as ``detail``, and the loop continues. That is deliberate and it is the
reason ``synapse.run`` is worth having: a tenant whose analysis blew up is a ROW an operator can
find, rather than a sweep that stopped at the third of twelve tenants and left the rest looking
as though they were never due. The caller learns something went wrong from the returned results
— ``__main__`` exits non-zero — rather than from the sweep dying.

THE ONE THING THAT DOES ABORT EVERYTHING is a refused provision (``ProvisionRefusedError``): a
rung above its analysis's ceiling, or an analysis no declaration claims. That is not one
tenant's bad day, it is the enablement table disagreeing with the code, and continuing would
mean acting on an estate nobody has validated.

PROVENANCE IS NOT OPTIONAL (D2). Nothing here constructs a ``Provenance``; the proposer does,
from the declaration and the resolution, and it RAISES if the declaration lacks a holdout or a
threshold it needs. That exception lands in the per-pair handler and the run is recorded as
``failed`` having appended NOTHING. An action without an arm can never be analysed, so failing
is strictly better than a log full of unattributable rows.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from dis_core.ids import new_uuid7
from synapse.core.action import Action, ActionEvent
from synapse.core.capability import CapabilityScope
from synapse.core.declaration_resolution import (
    DeclarationBlocked,
    DeclarationSatisfied,
    DeclarationUndeclared,
)
from synapse.core.provision import Provision, Rung
from synapse.core.slot import slot_for
from synapse.persistence.action_log_postgres import PostgresActionAppender
from synapse.persistence.provision_postgres import PostgresProvisionReader
from synapse.persistence.run_postgres import PostgresRunRecorder
from synapse.registry import max_rungs, plan_for, resolve_declaration

__all__ = ["SlotResult", "run_due"]


@dataclass(frozen=True)
class SlotResult:
    """What happened for one (tenant, analysis, slot). Returned, never printed from in here.

    A value rather than a log line so the CLI can decide the exit code and the format, and so a
    test can assert on the outcome without parsing text.
    """

    tenant_id: UUID
    analysis_id: str
    slot: date
    # None when the slot was skipped: there is no run to have an outcome.
    outcome: str | None
    actions_proposed: int
    actions_appended: int
    detail: str | None = None
    # Already finished by an earlier dispatch. Nothing ran.
    skipped: bool = False
    # Adopted a claimed-but-unfinished row: a previous execution died mid-run.
    taken_over: bool = False

    @property
    def failed(self) -> bool:
        return self.outcome == "failed"


async def run_due(
    *,
    reader_engine: AsyncEngine,
    writer_engine: AsyncEngine,
    now: datetime,
    dry_run: bool = False,
    only_tenant: UUID | None = None,
    only_analysis: str | None = None,
) -> Sequence[SlotResult]:
    """Run every provisioned pair that is due at ``now``.

    ``now`` IS A PARAMETER, never read from the clock in here. Same discipline as ``as_of`` on
    the evaluator and for the same payoff: "what would the sweep have done on the 1st" is
    answerable, and a slot boundary is testable without waiting for midnight. ``__main__``
    supplies ``datetime.now(UTC)``.

    ``dry_run`` resolves, evaluates and proposes but writes NOTHING — no run claimed, no action
    appended. It exists because D3 requires this be runnable by hand before it is scheduled, and
    the first hand-run of something that writes to an append-only log should be one that cannot.

    ``only_tenant`` and ``only_analysis`` narrow the sweep for an operator debugging one pair.
    They filter the enumeration; they do not bypass the envelope check, which has already run
    over the whole table by the time they apply.
    """
    provisions = await PostgresProvisionReader(reader_engine).active(max_rungs=max_rungs())
    due = [
        provision
        for provision in provisions
        if (only_tenant is None or provision.tenant_id == only_tenant)
        and (only_analysis is None or provision.analysis_id == only_analysis)
    ]

    results: list[SlotResult] = []
    for provision in due:
        results.append(
            await _run_one(
                provision=provision,
                reader_engine=reader_engine,
                writer_engine=writer_engine,
                now=now,
                dry_run=dry_run,
            )
        )
    return tuple(results)


async def _run_one(
    *,
    provision: Provision,
    reader_engine: AsyncEngine,
    writer_engine: AsyncEngine,
    now: datetime,
    dry_run: bool,
) -> SlotResult:
    """One pair, one slot. Never raises for an analytical failure; records it instead."""
    slot = slot_for(provision.cadence, provision.timezone, now)

    # THE RUNG IS REFUSED BEFORE ANYTHING IS CLAIMED. The loader has already established that
    # this rung is within the analysis's declared ceiling; this is the second, different check —
    # whether this BUILD can honour it at all. Nothing delivers anything, so any rung above
    # SHADOW is a promise the code cannot keep, and approximating it (computing but not
    # delivering, while recording that we ran at 'suggest') would put a false claim in the run
    # table. Enabling delivery means deleting this branch, which is a visible act.
    if provision.rung is not Rung.SHADOW:
        return SlotResult(
            tenant_id=provision.tenant_id,
            analysis_id=provision.analysis_id,
            slot=slot,
            outcome="failed",
            actions_proposed=0,
            actions_appended=0,
            detail=(
                f"rung {provision.rung.value!r} is within {provision.analysis_id}'s declared "
                "ceiling but nothing implements it: there is no delivery of any kind in this "
                "build. Refusing rather than running it as shadow, which would record a run at "
                "a rung that did not happen"
            ),
        )

    recorder = PostgresRunRecorder(writer_engine, provision.tenant_id)
    claim = None
    if not dry_run:
        claim = await recorder.claim(
            run_id=new_uuid7(),
            provision=provision,
            slot=slot,
            started_at=now,
        )
        if claim is None:
            return SlotResult(
                tenant_id=provision.tenant_id,
                analysis_id=provision.analysis_id,
                slot=slot,
                outcome=None,
                actions_proposed=0,
                actions_appended=0,
                skipped=True,
                detail="slot already finished by an earlier dispatch",
            )

    # ELAPSED IS MEASURED, THE ANCHOR IS INJECTED. finished_at used to be datetime.now(UTC)
    # while started_at came from `now`, which violates ck_run_finished_after_started the moment
    # the two disagree — and they disagree by design: `now` is a parameter precisely so a sweep
    # can be replayed for a past day or run at a boundary in a test. Anchoring the finish to the
    # same injected instant and adding a MONOTONIC elapsed keeps both timestamps in one clock
    # domain while still recording how long the analysis actually took.
    started = time.monotonic()
    proposed: Sequence[Action] = ()
    appended = 0
    outcome = "satisfied"
    detail: str | None = None
    try:
        resolution = await resolve_declaration(
            reader_engine,
            provision.analysis_id,
            CapabilityScope(tenant_id=provision.tenant_id),
        )
        match resolution:
            case DeclarationSatisfied():
                proposed = await _propose(resolution, slot)
                if not dry_run:
                    appended = await _append_all(writer_engine, provision.tenant_id, proposed, now)
            case DeclarationBlocked():
                outcome = "blocked"
                detail = f"blocked on {sorted(resolution.blocked)}"
            case DeclarationUndeclared():
                # Unreachable via the loader, which refuses an unknown analysis_id for the whole
                # enumeration. Recorded rather than asserted because the registry could change
                # under a long sweep, and a crash is a worse answer than a row saying so.
                outcome = "undeclared"
                detail = f"{provision.analysis_id!r} is not declared"
    except Exception as exc:  # noqa: BLE001 - one tenant's failure must not end the sweep
        outcome = "failed"
        detail = f"{type(exc).__name__}: {exc}"

    if not dry_run and claim is not None:
        await recorder.complete(
            run_id=claim.run_id,
            finished_at=now + timedelta(seconds=time.monotonic() - started),
            outcome=outcome,
            actions_proposed=len(proposed),
            actions_appended=appended,
            detail=detail,
        )

    return SlotResult(
        tenant_id=provision.tenant_id,
        analysis_id=provision.analysis_id,
        slot=slot,
        outcome=outcome,
        actions_proposed=len(proposed),
        actions_appended=appended,
        detail=detail,
        taken_over=bool(claim and claim.taken_over),
    )


async def _propose(resolution: DeclarationSatisfied, slot: date) -> Sequence[Action]:
    """Run the analysis's plan. ``as_of`` IS THE SLOT, and that is the load-bearing line.

    Not ``date.today()``. The slot is what makes a redelivered dispatch produce byte-identical
    actions, which is what lets ``uq_actions_idempotency`` — whose columns include ``as_of`` —
    suppress them. A second clock read here would give a retry after midnight a different
    ``as_of``, and the index would correctly conclude these are different actions and append a
    full duplicate set. The slot key on ``synapse.run`` and the idempotency index on
    ``synapse.actions`` only agree because both are derived from this one value.
    """
    plan = plan_for(resolution.declaration.id)
    if plan is None:
        # A declaration with no proposer: resolved, evaluated by nothing, produces no actions.
        # Legal, and recorded as a satisfied run with zero actions.
        return ()
    return await plan(resolution, slot)


async def _append_all(
    writer_engine: AsyncEngine,
    tenant_id: UUID,
    actions: Sequence[Action],
    recorded_at: datetime,
) -> int:
    """Append every action, returning how many were NEW.

    ``event_id`` and ``recorded_at`` are minted HERE because ``synapse.core`` mints nothing:
    ``uuid4`` is banned project-wide and a pure module that reads a clock cannot be tested at a
    boundary. This is the layer allowed to have both.

    A FRESH ``event_id`` PER APPEND, INCLUDING ON A RETRY, and that is correct rather than
    careless. Identity is not what deduplicates an action — the natural key plus the payload hash
    is — so a retry mints a new event_id, collides on the index, and is suppressed. Deriving a
    deterministic event_id from the payload would make the id redundant with the index and would
    quietly prevent a legitimate correction from ever being recorded.
    """
    appender = PostgresActionAppender(writer_engine, tenant_id)
    landed = 0
    for action in actions:
        event = ActionEvent(
            event_id=new_uuid7(),
            recorded_at=recorded_at,
            action=action,
        )
        if await appender.append(event):
            landed += 1
    return landed


def summarise(results: Sequence[SlotResult]) -> Mapping[str, int]:
    """Counts by outcome, for a one-line operator summary. ``skipped`` is counted separately."""
    counts: dict[str, int] = {}
    for result in results:
        key = "skipped" if result.skipped else str(result.outcome)
        counts[key] = counts.get(key, 0) + 1
    return counts
