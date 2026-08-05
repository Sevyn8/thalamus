"""Reading ``synapse.provision``: which (tenant, analysis) pairs are active.

PLATFORM SCOPE, AND IT IS THE FIRST THING IN SYNAPSE THAT NEEDS IT. Every reader before this
one answered a question about ONE tenant and ran under ``rls_session``. Enumerating what is
provisioned is the opposite shape — it is a question ACROSS tenants, and it is the orchestrator's
entire input. ``dis_rls.rls_platform_session(engine, None)`` is exactly that posture and already
exists: see-all reads, and writes NOTHING, because the tenant GUC is set to ``''`` and the
policy's ``NULLIF(..., '')::uuid`` maps it to NULL so ``WITH CHECK`` matches no row. An
enumerating session that physically cannot write is the right one for a pass whose only job is
to look.

THE ENVELOPE IS CHECKED HERE, AT LOAD, and the ceiling is INJECTED rather than imported. The
declarations live in ``synapse.registry``, which sits ABOVE this package in the import-linter
layer order — so this module cannot reach them, and should not: a persistence module that
imported the registry would invert the layering to answer a question the caller already knows
the answer to. The caller passes ``max_rungs``; the same discipline as resolvers taking their
engine by injection.

Checking at load rather than at use is what makes an over-privileged row harmless. A provision
naming a rung its analysis has not earned never reaches an orchestrator, so there is no path on
which "we checked the rung" could be forgotten.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_rls import rls_platform_session
from synapse.core.errors import ProvisionRefusedError
from synapse.core.provision import Cadence, Provision, Rung, rung_rank

__all__ = ["PostgresProvisionReader", "check_envelope", "project"]


# Every column Provision needs, and no ``SELECT *``: a column added to the table must be a
# deliberate addition here too, rather than arriving unvalidated in a mapping.
#
# ORDERED BY (analysis_id, tenant_id) to match ix_provision_active, so the enumeration is a
# range scan over the partial index rather than a sort. The order is also STABLE, which makes a
# run's per-tenant sequence reproducible between dispatches — useful when reading two runs' logs
# side by side.
_SELECT_ACTIVE = text(
    """
    SELECT tenant_id, analysis_id, cadence, rung, timezone, enabled_at
      FROM synapse.provision
     WHERE disabled_at IS NULL
     ORDER BY analysis_id, tenant_id
    """
)

# A provisioned estate is operator-entered, one row per tenant per analysis. Thousands would
# mean something has gone wrong upstream rather than that the business grew, and an unbounded
# read feeding an unbounded loop of database work is how a scheduled job becomes an outage.
_MAX_PROVISIONS = 5_000


def project(row: Mapping[str, Any]) -> Provision:
    """One row to a ``Provision``, validating through the frozen type rather than around it.

    ``Cadence`` and ``Rung`` are constructed from the stored text, so a value the CHECK
    constraint admits but the enum does not — the state after a migration adds a member the code
    does not know — raises here instead of flowing on as a string that compares unequal to
    everything.
    """
    return Provision(
        tenant_id=row["tenant_id"] if isinstance(row["tenant_id"], UUID) else UUID(str(row["tenant_id"])),
        analysis_id=row["analysis_id"],
        cadence=Cadence(row["cadence"]),
        rung=Rung(row["rung"]),
        timezone=row["timezone"],
        enabled_at=row["enabled_at"],
    )


def check_envelope(provisions: Sequence[Provision], max_rungs: Mapping[str, Rung]) -> None:
    """Refuse the whole set if any provision is outside what its analysis declares.

    A SEPARATE PURE FUNCTION RATHER THAN INLINE IN ``active``, and the reason is a recorded
    property of this repo rather than a style preference: the integration suite only runs inside
    a staging window, so a guard reachable only through a live query is a guard that goes
    unexercised for as long as the gap between windows. This one is the envelope — the thing
    standing between a hand-edited table and an analysis acting past its maturity — and it is
    checked by the offline suite on every run.

    Raises ``ProvisionRefusedError`` for either cause, naming every offending row rather than the
    first: an operator fixing one typo should not have to run the sweep again to find the next.
    """
    unknown = sorted({p.analysis_id for p in provisions if p.analysis_id not in max_rungs})
    if unknown:
        raise ProvisionRefusedError(
            f"provision rows name analyses that no declaration claims: {unknown}. A provision "
            "for an analysis that does not exist enables nothing while looking enabled. "
            f"Declared analyses are {sorted(max_rungs)}"
        )

    exceeded = [
        (p.tenant_id, p.analysis_id, p.rung.value, max_rungs[p.analysis_id].value)
        for p in provisions
        if rung_rank(p.rung) > rung_rank(max_rungs[p.analysis_id])
    ]
    if exceeded:
        raise ProvisionRefusedError(
            "provision rows exceed their analysis's declared max_rung — the envelope is code "
            "and is not editable from this table: "
            + "; ".join(
                f"tenant {tenant} / {analysis} asks for {asked!r}, ceiling is {ceiling!r}"
                for tenant, analysis, asked, ceiling in exceeded
            )
        )


class PostgresProvisionReader:
    """Every active provision, across all tenants, checked against the declared envelope."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def active(self, *, max_rungs: Mapping[str, Rung]) -> Sequence[Provision]:
        """Load every active provision. Refuse the whole set if any row is illegal.

        ``max_rungs`` maps analysis id to the ceiling that analysis declares. A pair not present
        in it names an analysis no declaration claims.

        REFUSES THE ENUMERATION RATHER THAN DROPPING THE ROW. Skipping a bad provision would
        mean a tenant silently stops being analysed while everything reports success — the exact
        shape of failure this table was added to make visible. One bad row stopping the sweep is
        loud, and an operator fixing a typo is a one-line UPDATE.
        """
        async with rls_platform_session(self._engine, None) as conn:
            rows = (await conn.execute(_SELECT_ACTIVE)).mappings().all()

        if len(rows) > _MAX_PROVISIONS:
            raise ProvisionRefusedError(
                f"synapse.provision holds {len(rows)} active rows, more than the "
                f"{_MAX_PROVISIONS} this reader will load. That is far past an operator-entered "
                "estate; check for a bulk insert before raising the cap"
            )

        # dict(row) rather than the RowMapping itself, matching action_log_postgres: a
        # RowMapping is not a Mapping[str, Any] to mypy, and projecting through a plain dict
        # keeps the projector testable with an ordinary literal.
        provisions = [project(dict(row)) for row in rows]

        check_envelope(provisions, max_rungs)
        return tuple(provisions)
