"""The thing that makes Synapse run without a test running it.

Until this package existed, ``dead_stock`` executed exactly when someone executed it. Everything
needed to produce an action was built — resolve, fetch, evaluate, propose, append — and nothing
decided to. Shadow mode was a design rather than a state the system was in.

WHAT AN ORCHESTRATOR IS HERE, and what it is not. This is a WORKER: it enumerates provisioned
(tenant, analysis) pairs, works out which slot each is due for, and does the analysis inline —
resolving, evaluating, proposing and appending in its own process. It is deliberately NOT a
dispatcher that triggers other jobs. Those are different shapes, and the connector case, which
looks superficially identical, is the dispatcher one: it would trigger N executions and do no
work itself. Building one abstraction over both would force this side to dispatch per-tenant
jobs, which for one tenant is pure overhead. (The connector case is also blocked on its own data
model — ``config.sources.schedule`` is a free-text human label, and DIS's own
``telemetry.connector_health`` DDL says a machine cadence does not exist — so there is currently
nothing to generalise toward.)

THE ONE PIECE KEPT GENERAL is ``synapse.core.slot``: pure over (cadence, timezone, instant), no
Synapse types. That is the half a future dispatcher could reuse unchanged, and it costs nothing
to keep clean.

SHADOW ONLY. Nothing here delivers anything. No channel, no notification, no escalation. A run
computes, records to ``synapse.actions``, updates ``synapse.run``, and shows nobody. Any rung
other than ``SHADOW`` is REFUSED rather than approximated — see ``runner.run_due`` — because
enabling delivery must be the deletion of an explicit refusal rather than the discovery that
something already half-worked.

TWO RLS SCOPES IN ONE PROCESS, which is the structural thing to understand before reading
``runner``:

  - PLATFORM, no tenant, to ENUMERATE. Reading which tenants have what provisioned is a question
    across tenants. ``rls_platform_session(engine, None)`` sees every row and can write none.
  - TENANT, per pair, to ACT. Claiming a run and appending actions are writes, and the policies'
    ``WITH CHECK`` pins them to the acted-for tenant.

The enumerating session physically cannot write, and the acting session physically cannot touch
another tenant. Neither property depends on this package being careful.

TWO ENGINES: ``synapse_reader`` for everything read, ``synapse_writer``
for the action log and the run table. The split is a grant, not a convention.
"""

from __future__ import annotations

from synapse.orchestrator.runner import SlotResult, run_due

__all__ = ["SlotResult", "run_due"]
