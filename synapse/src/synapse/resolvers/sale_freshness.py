"""How recent a tenant's newest sale is. One aggregate, PLATFORM-scoped, across tenants.

WHY THIS IS A RESOLVER AND NOT PART OF THE ORCHESTRATOR. It reads ``canonical``, and in this plane
only resolvers may — D6, enforced by ``tests/unit/test_table_name_containment.py``, which is the
mechanism rather than a belt (an import graph cannot see a table name because a table name is a
string). The first draft of this put the query in ``orchestrator/freshness.py`` and that test
caught it immediately, which is the guard doing exactly what it was written for.

WHAT IT IS NOT: a declared capability. There is no descriptor, no grain, no freshness contract and
nothing in the registry requires it. It answers an OPERATIONAL question — "has this tenant's data
stopped arriving" — for the alerting path, and deliberately does not pretend to be an analytical
input. A capability implies something may build an action on it; nothing may build an action on
this.

PLATFORM, NOT TENANT-SCOPED, and that is the opposite of every other resolver here. The others take
a ``CapabilityScope`` and open ``rls_session`` for one tenant, because an analysis acts for one
tenant. This one is asked "which tenants have gone quiet", which is a question ACROSS tenants — so
it uses ``rls_platform_session(engine, None)``, which sees every row and (the tenant GUC being
``''``) can write none.

THE COST, stated rather than waved at. One aggregate per tenant per sweep:

    SELECT max(event_date) FROM canonical.store_sku_sale_events WHERE tenant_id = :t

There is NO index on ``event_date``. The available indexes lead ``(tenant_id, store_id,
source_sale_timestamp)`` and ``(tenant_id, store_id, sku_id, source_sale_timestamp)``, so the tenant
predicate is index-supported and the aggregate runs over that tenant's slice. At present volume —
613 sale events for the only live tenant — negligible, and it runs once per tenant per DAY, not per
pair and not per SKU. If it stops being negligible the fix is an index on ``(tenant_id,
event_date)``; adding one now would be optimising against hundreds of rows.

WHY NOT REUSE WHAT THE ANALYSES ALREADY FETCH. ``dead_stock`` resolves ``last_sale_at`` and
``stockout_risk`` resolves ``daily_series``, and either would yield the date — but not at a layer
that can log it. ``runner._run_one`` holds a ``DeclarationSatisfied`` carrying ``fetch`` CALLABLES,
not rows; the PLAN fetches. ``Satisfied.fetch`` has no memoisation, so calling it again would issue
a second full series read rather than reusing the first, and threading the value back out of the
plan is a Plan-signature change — the same blocker that deferred populating ``run.detail``
(outstanding item 4). One cheap aggregate beats quietly taking on deferred work.

And ``daily_series`` is WINDOWED (``window_days``: 28 and 14 in slice 7), so for a tenant stale
beyond its window it resolves EMPTY — no date at all, in exactly the case most worth reporting.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_rls import rls_platform_session

__all__ = ["resolve_latest_sale_dates"]

# SALE ONLY is NOT filtered here, and that is a deliberate difference from ``last_sale_at``. That
# resolver excludes RETURN and VOID because a return is not movement and would make a dead SKU look
# alive. This asks a different question — "is data still ARRIVING" — and a return is data arriving.
# A tenant sending nothing but returns has a live pipeline and a different problem.
_LATEST_SALE = text(
    """
    SELECT max(event_date) AS latest_sale
      FROM canonical.store_sku_sale_events
     WHERE tenant_id = CAST(:tenant AS uuid)
    """
)


async def resolve_latest_sale_dates(
    engine: AsyncEngine, tenant_ids: Iterable[UUID]
) -> Mapping[UUID, date | None]:
    """Newest ``event_date`` per tenant. ``None`` when the tenant has never had a sale event.

    ``None`` IS NOT ZERO AND NOT A DEFAULT. "Never sold" and "sold long ago" need different words
    from whatever consumes this, so the absence is returned as absence rather than collapsed into a
    very old date — the same reason ``LastSaleAtRow`` has no nullable date and represents "never
    sold" as a missing row.

    Every requested tenant appears in the result, so a caller iterating the mapping cannot silently
    skip one that has no data — which is the tenant most worth reporting.
    """
    out: dict[UUID, date | None] = {}
    async with rls_platform_session(engine, None) as conn:
        for tenant_id in tenant_ids:
            value = (await conn.execute(_LATEST_SALE, {"tenant": str(tenant_id)})).scalar_one_or_none()
            if value is None:
                out[tenant_id] = None
            else:
                out[tenant_id] = value if isinstance(value, date) else date.fromisoformat(str(value))
    return out
