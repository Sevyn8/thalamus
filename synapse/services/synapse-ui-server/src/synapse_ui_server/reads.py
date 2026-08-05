"""Every database read this service performs. All SELECT, all PLATFORM, none of them a write.

ONE ENGINE, BUILT FROM THE READER DSN. There is no writer engine in this module because there is
no writer DSN in the config — see the package docstring. A future write path has to add both,
visibly.

PLATFORM SCOPE THROUGHOUT. ``rls_platform_session(None)`` sees every tenant and, because the
tenant GUC is set to ``''`` and every policy's ``WITH CHECK`` compares against it, can write
nothing. That posture is exactly right for a console: the fleet screen's whole job is to cross
tenants, and the session it uses is physically incapable of modifying what it reads.

AND THE GUCs ARE NOT OPTIONAL FOR THE READ EITHER. ``synapse.provision``, ``synapse.run``,
``synapse.actions`` and both canonical tables are FORCE ROW LEVEL SECURITY. A session without
``app.user_type`` matches ZERO ROWS AND RAISES NOTHING — for the owner, and for Cloud SQL's
``postgres``, which is NOSUPERUSER NOBYPASSRLS like anything else. Six incidents in this project
have come from that silent zero. ``rls_platform_session`` sets it; nothing here opens a raw
connection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_rls import rls_platform_session

__all__ = [
    "FleetRow",
    "RunRow",
    "TenantDetail",
    "fleet",
    "runs",
    "tenant_detail",
]

# A console page, not an export. Bounding every read means a pathological estate degrades the
# page rather than the service, and the number is stated rather than implied by a scroll bar.
_MAX_ROWS = 500


@dataclass(frozen=True)
class FleetRow:
    """One tenant on the fleet screen, whether or not Synapse runs for it.

    EVERY MIRRORED TENANT APPEARS, not only provisioned ones. A tenant with nothing on is a real
    state the screen must show — it is how an operator sees who could be enabled — and a LEFT
    JOIN is what keeps "not provisioned" distinct from "provisioned and idle".
    """

    tenant_id: UUID
    name: str
    analyses_running: int
    actions_recorded: int
    last_run_slot: date | None
    # None when the tenant has no sale events at all, which is different from stale.
    latest_sale: date | None
    stores: int
    products: int


@dataclass(frozen=True)
class TenantDetail:
    """One tenant's panel. Counts and per-analysis state; no product is named."""

    tenant_id: UUID
    name: str
    products: int
    stores: int
    sales_seen: int
    latest_sale: date | None
    actions_recorded: int
    analyses: tuple[AnalysisState, ...]


@dataclass(frozen=True)
class AnalysisState:
    """One provisioned analysis for one tenant, with its most recent run.

    ``outcome`` and the two counts come from ``synapse.run``; ``detail`` is the column that
    exists and is NOT populated (outstanding item 4). It is carried as ``None`` rather than
    omitted so the UI can say WHY the refusal breakdown is missing instead of leaving a gap.
    """

    analysis_id: str
    cadence: str
    rung: str
    timezone: str
    enabled_at: datetime
    last_slot: date | None
    last_outcome: str | None
    actions_proposed: int | None
    actions_appended: int | None
    detail: str | None


@dataclass(frozen=True)
class RunRow:
    """One row of the runs screen. The denominator, newest first."""

    run_id: UUID
    tenant_id: UUID
    tenant_name: str
    analysis_id: str
    slot: date
    outcome: str | None
    actions_proposed: int | None
    actions_appended: int | None
    started_at: datetime
    finished_at: datetime | None


# ---------------------------------------------------------------------------
# The one cross-tenant query
# ---------------------------------------------------------------------------
#
# LEFT JOINs from the tenant mirror, so a tenant with no provision, no run and no sale still
# produces a row. Aggregated in SQL rather than in Python: pulling every action and counting
# them here would hold every sku_id in memory for a screen that renders none of them.
_FLEET = text(
    """
    SELECT t.tenant_id,
           t.name,
           COALESCE(p.analyses_running, 0)  AS analyses_running,
           COALESCE(a.actions_recorded, 0)  AS actions_recorded,
           r.last_run_slot,
           s.latest_sale,
           COALESCE(st.stores, 0)           AS stores,
           COALESCE(cp.products, 0)         AS products
      FROM identity_mirror.tenants t
      LEFT JOIN (SELECT tenant_id, count(*) AS analyses_running
                   FROM synapse.provision WHERE disabled_at IS NULL
                  GROUP BY tenant_id) p  ON p.tenant_id = t.tenant_id
      LEFT JOIN (SELECT tenant_id, count(*) AS actions_recorded
                   FROM synapse.actions GROUP BY tenant_id) a ON a.tenant_id = t.tenant_id
      LEFT JOIN (SELECT tenant_id, max(slot) AS last_run_slot
                   FROM synapse.run GROUP BY tenant_id) r  ON r.tenant_id = t.tenant_id
      LEFT JOIN (SELECT tenant_id, max(event_date) AS latest_sale
                   FROM canonical.store_sku_sale_events GROUP BY tenant_id) s
             ON s.tenant_id = t.tenant_id
      LEFT JOIN (SELECT tenant_id, count(*) AS stores
                   FROM identity_mirror.stores GROUP BY tenant_id) st ON st.tenant_id = t.tenant_id
      LEFT JOIN (SELECT tenant_id, count(*) AS products
                   FROM canonical.store_sku_current_position GROUP BY tenant_id) cp
             ON cp.tenant_id = t.tenant_id
     ORDER BY analyses_running DESC, t.name
     LIMIT :limit
    """
)


async def fleet(engine: AsyncEngine) -> tuple[FleetRow, ...]:
    """Every mirrored tenant, with what Synapse knows about it.

    ``latest_sale`` IS THE ONLY THING THAT CAN SEE A STALE TENANT. A tenant whose data stopped
    arriving produces runs that SUCCEED every day — the analyses refuse per series, the run
    completes, the execution is green — so no execution-status alert can ever notice. This
    column is currently the only mechanism in the entire project that surfaces it, which is why
    it is computed here rather than left to a future alert.
    """
    async with rls_platform_session(engine, None) as conn:
        rows = (await conn.execute(_FLEET, {"limit": _MAX_ROWS})).mappings().all()
    return tuple(
        FleetRow(
            tenant_id=_as_uuid(row["tenant_id"]),
            name=row["name"],
            analyses_running=int(row["analyses_running"]),
            actions_recorded=int(row["actions_recorded"]),
            last_run_slot=row["last_run_slot"],
            latest_sale=row["latest_sale"],
            stores=int(row["stores"]),
            products=int(row["products"]),
        )
        for row in rows
    )


_TENANT = text(
    """
    SELECT t.tenant_id, t.name,
           COALESCE(cp.products, 0) AS products,
           COALESCE(st.stores, 0)   AS stores,
           COALESCE(se.sales, 0)    AS sales_seen,
           se.latest_sale,
           COALESCE(a.actions, 0)   AS actions_recorded
      FROM identity_mirror.tenants t
      LEFT JOIN (SELECT tenant_id, count(*) AS products
                   FROM canonical.store_sku_current_position GROUP BY tenant_id) cp
             ON cp.tenant_id = t.tenant_id
      LEFT JOIN (SELECT tenant_id, count(*) AS stores
                   FROM identity_mirror.stores GROUP BY tenant_id) st ON st.tenant_id = t.tenant_id
      LEFT JOIN (SELECT tenant_id, count(*) AS sales, max(event_date) AS latest_sale
                   FROM canonical.store_sku_sale_events GROUP BY tenant_id) se
             ON se.tenant_id = t.tenant_id
      LEFT JOIN (SELECT tenant_id, count(*) AS actions
                   FROM synapse.actions GROUP BY tenant_id) a ON a.tenant_id = t.tenant_id
     WHERE t.tenant_id = CAST(:tenant AS uuid)
    """
)

# The latest run per (tenant, analysis). DISTINCT ON is the Postgres idiom and avoids a window
# function over a table that will stay small for a long time.
_TENANT_ANALYSES = text(
    """
    SELECT p.analysis_id, p.cadence, p.rung, p.timezone, p.enabled_at,
           r.slot AS last_slot, r.outcome AS last_outcome,
           r.actions_proposed, r.actions_appended, r.detail
      FROM synapse.provision p
      LEFT JOIN LATERAL (
            SELECT slot, outcome, actions_proposed, actions_appended, detail
              FROM synapse.run rr
             WHERE rr.tenant_id = p.tenant_id AND rr.analysis_id = p.analysis_id
             ORDER BY rr.slot DESC
             LIMIT 1
      ) r ON TRUE
     WHERE p.tenant_id = CAST(:tenant AS uuid) AND p.disabled_at IS NULL
     ORDER BY p.analysis_id
    """
)


async def tenant_detail(engine: AsyncEngine, tenant_id: UUID) -> TenantDetail | None:
    """One tenant. ``None`` when the id is not in the mirror at all.

    NOT AN EMPTY DETAIL FOR AN UNKNOWN TENANT. A mistyped id returning zeros looks exactly like a
    real tenant with nothing on, and this project has already paid for that confusion once — a
    mistyped tenant in ``synapse.provision`` produces healthy zero-action runs for ever.
    """
    async with rls_platform_session(engine, None) as conn:
        header = (await conn.execute(_TENANT, {"tenant": str(tenant_id)})).mappings().one_or_none()
        if header is None:
            return None
        analyses = (await conn.execute(_TENANT_ANALYSES, {"tenant": str(tenant_id)})).mappings().all()

    return TenantDetail(
        tenant_id=_as_uuid(header["tenant_id"]),
        name=header["name"],
        products=int(header["products"]),
        stores=int(header["stores"]),
        sales_seen=int(header["sales_seen"]),
        latest_sale=header["latest_sale"],
        actions_recorded=int(header["actions_recorded"]),
        analyses=tuple(
            AnalysisState(
                analysis_id=row["analysis_id"],
                cadence=row["cadence"],
                rung=row["rung"],
                timezone=row["timezone"],
                enabled_at=row["enabled_at"],
                last_slot=row["last_slot"],
                last_outcome=row["last_outcome"],
                actions_proposed=row["actions_proposed"],
                actions_appended=row["actions_appended"],
                detail=row["detail"],
            )
            for row in analyses
        ),
    )


_RUNS = text(
    """
    SELECT r.run_id, r.tenant_id, t.name AS tenant_name, r.analysis_id, r.slot,
           r.outcome, r.actions_proposed, r.actions_appended, r.started_at, r.finished_at
      FROM synapse.run r
      LEFT JOIN identity_mirror.tenants t ON t.tenant_id = r.tenant_id
     ORDER BY r.slot DESC, r.started_at DESC
     LIMIT :limit
    """
)


async def runs(engine: AsyncEngine, *, limit: int = 100) -> tuple[RunRow, ...]:
    """The run log, newest slot first.

    ONE ROW PER SLOT, which is what the table holds. The spec's "dispatches against that day"
    panel was dropped rather than deferred: those lines live in Cloud Run execution history, a
    different source needing the Run Admin API and an IAM grant, whose data ages out — a new
    external dependency for one decorative panel. Fabricating them from the run row would have
    been worse than not showing them.
    """
    bounded = max(1, min(limit, _MAX_ROWS))
    async with rls_platform_session(engine, None) as conn:
        rows = (await conn.execute(_RUNS, {"limit": bounded})).mappings().all()
    return tuple(
        RunRow(
            run_id=_as_uuid(row["run_id"]),
            tenant_id=_as_uuid(row["tenant_id"]),
            # A run for a tenant the mirror has lost is still a run. Naming it rather than
            # dropping the row: synapse.run deliberately has no FK into any DIS schema, because
            # an append-only history must outlive what it references.
            tenant_name=row["tenant_name"] or "(not in the tenant mirror)",
            analysis_id=row["analysis_id"],
            slot=row["slot"],
            outcome=row["outcome"],
            actions_proposed=row["actions_proposed"],
            actions_appended=row["actions_appended"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )
        for row in rows
    )


def _as_uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))
