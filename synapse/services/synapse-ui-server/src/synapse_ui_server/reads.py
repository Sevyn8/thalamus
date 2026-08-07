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

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
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
    "tenant_runs",
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
    # Open = nobody has closed it. See _FLEET's LATERAL for what "closed" means.
    open_alerts: int
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

    ``outcome``, the two counts, ``detail`` and ``refusals`` all come from ``synapse.run``.

    ``refusals`` IS THE ONE THAT CHANGED IN SLICE 5b. This docstring used to say detail "exists
    and is NOT populated (outstanding item 4)", which was true: nothing threaded a breakdown onto
    the run row, so a monitor that refused every series looked identical to one that found
    nothing. Item 4 is closed — the plan returns its refusals and the orchestrator records them —
    and this carries the result so the tenant page can say "12 series refused — sales data too
    old" instead of showing a bare zero.
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
    # {reason: count} over the closed vocabulary; empty when no refusals were recorded.
    # Optional only because a monitor may have NO last run at all, in which case the whole
    # LEFT JOIN row is absent rather than empty. See RunRow.refusals.
    refusals: Mapping[str, int] | None


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
    # WHAT THE ANALYSIS COULD NOT ASSESS, as {reason: count}. Read straight through as the
    # database's own JSONB rather than re-typed here: the vocabulary belongs to
    # synapse.core.stockout_risk, and this service deliberately imports no analysis code — a BFF
    # that owned a copy of the reason set would be a second place to update when one is added.
    #
    # NOT NULL IN THE DATABASE (migration 0005), so a run row always carries a map: empty
    # means no refusals were recorded, and "this run assessed nothing at all" is what
    # `outcome` says rather than a second encoding here.
    #
    # Typed optional ANYWAY, and deliberately: the console is deployed separately from this
    # service and from the migration, so a client may read a row written before 0005 landed.
    # Rendering "no refusals" for a row that has not been told is a claim; None is not.
    refusals: Mapping[str, int] | None


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
           COALESCE(o.open_alerts, 0)       AS open_alerts,
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
      -- OPEN ALERTS, resolved per TARGET like every other lifecycle read (slice 5d).
      -- An alert is open unless its target's LATEST decision is a dismissal or a snooze
      -- that has not lapsed. Acknowledged still counts as open: it says somebody has
      -- seen it and left it standing, which is not the same as closing it.
      --
      -- ALONGSIDE actions_recorded, NOT INSTEAD OF IT. That count is the attribution
      -- denominator D1 protects; redefining it under the same name would silently change
      -- what an older screenshot meant.
      LEFT JOIN (
          SELECT act.tenant_id, count(*) AS open_alerts
            FROM synapse.actions act
            LEFT JOIN LATERAL (
                SELECT DISTINCT ON (e.tenant_id, e.declaration_id, e.target)
                       e.verb, e.snoozed_until
                  FROM synapse.action_events e
                 WHERE e.tenant_id = act.tenant_id
                   AND e.declaration_id = act.declaration_id
                   AND e.target = act.target
                 ORDER BY e.tenant_id, e.declaration_id, e.target,
                          e.recorded_at DESC, e.lifecycle_event_id DESC
            ) le ON TRUE
           WHERE le.verb IS NULL
              OR le.verb = 'acknowledge'
              OR (le.verb = 'snooze' AND le.snoozed_until < CURRENT_DATE)
           GROUP BY act.tenant_id
      ) o ON o.tenant_id = t.tenant_id
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
            open_alerts=int(row["open_alerts"]),
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
           r.actions_proposed, r.actions_appended, r.detail, r.refusals
      FROM synapse.provision p
      LEFT JOIN LATERAL (
            SELECT slot, outcome, actions_proposed, actions_appended, detail, refusals
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
                refusals=row["refusals"],
                actions_appended=row["actions_appended"],
                detail=row["detail"],
            )
            for row in analyses
        ),
    )


_RUNS = text(
    """
    SELECT r.run_id, r.tenant_id, t.name AS tenant_name, r.analysis_id, r.slot,
           r.outcome, r.actions_proposed, r.actions_appended, r.started_at, r.finished_at,
           r.refusals
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
            refusals=row["refusals"],
        )
        for row in rows
    )


# The tenant filter, and nothing else changes. Identical projection, join and ordering to
# ``_RUNS`` so the two lists cannot disagree about what a run row IS — a second shape here would
# be a second source of truth for the same table, which is the duplication class this project
# keeps paying for.
_TENANT_RUNS = text(
    """
    SELECT r.run_id, r.tenant_id, t.name AS tenant_name, r.analysis_id, r.slot,
           r.outcome, r.actions_proposed, r.actions_appended, r.started_at, r.finished_at,
           r.refusals
      FROM synapse.run r
      LEFT JOIN identity_mirror.tenants t ON t.tenant_id = r.tenant_id
     WHERE r.tenant_id = CAST(:tenant AS uuid)
     ORDER BY r.slot DESC, r.started_at DESC
     LIMIT :limit
    """
)

# A PK lookup, run in the SAME session as the history so both see one consistent snapshot.
# identity_mirror is the authority on whether a tenant exists at all — synapse.run deliberately
# has no FK into it, so an absence of runs says nothing about whether the tenant is real.
_TENANT_EXISTS = text("SELECT 1 FROM identity_mirror.tenants WHERE tenant_id = CAST(:tenant AS uuid)")


async def tenant_runs(engine: AsyncEngine, tenant_id: UUID, *, limit: int = 100) -> tuple[RunRow, ...] | None:
    """One tenant's runs, newest slot first. ``None`` when the id is not in the mirror at all.

    THE None IS THE POINT, and it mirrors ``tenant_detail`` for the same reason: an empty history
    for a mistyped id is indistinguishable from a real tenant that has never run. The caller
    turns it into a 404 rather than an empty list, so a typo reads as a typo.

    WHY THIS EXISTS AT ALL. The tenant page previously fetched the FLEET-WIDE ``/runs`` at its
    maximum limit and filtered client-side on ``tenant_id``. That works and it silently
    truncates: a busy fleet pushes an individual tenant's older runs past the cap, and the page
    cannot tell a tenant with no history from one whose history fell off the end. The caption
    admitted it on screen, which was honest and is not a substitute for the query being right.

    PLATFORM SESSION, like every read here. ``synapse.run`` is FORCE ROW LEVEL SECURITY: a
    session without ``app.user_type`` matches zero rows and raises nothing, so a raw connection
    would return an empty history for every tenant and look like a quiet fleet.
    """
    bounded = max(1, min(limit, _MAX_ROWS))
    async with rls_platform_session(engine, None) as conn:
        exists = (await conn.execute(_TENANT_EXISTS, {"tenant": str(tenant_id)})).first()
        if exists is None:
            return None
        rows = (
            (await conn.execute(_TENANT_RUNS, {"tenant": str(tenant_id), "limit": bounded})).mappings().all()
        )
    return tuple(
        RunRow(
            run_id=_as_uuid(row["run_id"]),
            tenant_id=_as_uuid(row["tenant_id"]),
            tenant_name=row["tenant_name"] or "(not in the tenant mirror)",
            analysis_id=row["analysis_id"],
            slot=row["slot"],
            outcome=row["outcome"],
            actions_proposed=row["actions_proposed"],
            actions_appended=row["actions_appended"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            refusals=row["refusals"],
        )
        for row in rows
    )


def _as_uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


# ---------------------------------------------------------------------------
# Alerts: the first per-ACTION reads in this service (slice 5c)
# ---------------------------------------------------------------------------
#
# EVERYTHING ABOVE COUNTS ACTIONS; THESE TWO RETURN THEM. `synapse.actions` appeared in this
# module only as `count(*)` subqueries, which is why the console has never shown an individual
# alert and why the tenant page's Alerts section aggregates per MONITOR rather than listing
# alerts. A detail page needs a row to click from as well as one to click to, so this is a pair.
#
# PLATFORM ONLY, AND THE PAYLOAD IS THE REASON. These rows carry sku_id, product_name and
# store_name — every one of them in tenant_view_contract.FORBIDDEN_TENANT_FIELDS. A tenant-facing
# surface reusing either of these is the leak that contract exists to prevent, which is what
# test_alert_detail.py's negative test asserts structurally rather than by review.
#
# BOTH JOINS ARE LEFT, and that is not defensive habit. `synapse.actions` deliberately carries no
# foreign key into any DIS schema — an append-only log must outlive what it references — so a
# delisted SKU or a closed store must still render its alert rather than drop the row.
#
# store_id / sku_id ARE STORED GENERATED COLUMNS off `target` (actions.sql:148-156), so neither
# query extracts JSONB to join.

_ALERT_COLUMNS = """
           a.event_id, a.as_of, a.recorded_at, a.declaration_id, a.declaration_version,
           a.verb, a.arm, a.expires_on, a.quantity_at_stake,
           a.days_since_last_sale, a.days_of_cover, a.thresholds,
           a.store_id, a.sku_id, a.target,
           s.name AS store_name,
           p.product_name,
           p.stock_qty AS current_stock_qty,
           le.verb AS lifecycle_verb,
           le.reason AS lifecycle_reason,
           le.snoozed_until AS lifecycle_snoozed_until,
           le.recorded_at AS lifecycle_recorded_at,
           le.actor_subject AS lifecycle_actor
"""

# LIFECYCLE STATE IS DERIVED AT READ TIME, PER TARGET (slice 5d).
#
# PER TARGET, NOT PER EVENT, and that is the whole semantic. An operator who snoozes means
# "stop showing me this product at this store" — tomorrow's detection of the same thing is a
# NEW row with a new event_id, so a per-event match would evaporate on exactly the alert the
# snooze was meant to silence. The event records (declaration_id, target), the same key the
# actions idempotency index uses, and this joins on it.
#
# DISTINCT ON takes the LATEST event for the target: a dismissal after a snooze wins, and so
# does a fresh snooze after a lapsed one. Ties broken by lifecycle_event_id so the answer is
# stable rather than whichever row the planner reached first.
#
# NOTHING HERE SUPPRESSES A DETECTION. This is a JOIN on a read; the orchestrator does not
# read this table and keeps recording every slot. A snoozed target still accumulates rows in
# synapse.actions, which is what makes the post-expiry history complete.
_LIFECYCLE_JOIN = """
      LEFT JOIN LATERAL (
          SELECT DISTINCT ON (e.tenant_id, e.declaration_id, e.target)
                 e.verb, e.reason, e.snoozed_until, e.recorded_at, e.actor_subject
            FROM synapse.action_events e
           WHERE e.tenant_id = a.tenant_id
             AND e.declaration_id = a.declaration_id
             AND e.target = a.target
           ORDER BY e.tenant_id, e.declaration_id, e.target,
                    e.recorded_at DESC, e.lifecycle_event_id DESC
      ) le ON TRUE
"""

_ALERT_JOINS = f"""
      FROM synapse.actions a
      LEFT JOIN identity_mirror.stores s
             ON s.store_id = a.store_id
      LEFT JOIN canonical.store_sku_current_position p
             ON p.tenant_id = a.tenant_id AND p.store_id = a.store_id AND p.sku_id = a.sku_id
      {_LIFECYCLE_JOIN}
"""

_TENANT_ALERTS = text(
    f"""
    SELECT {_ALERT_COLUMNS}
    {_ALERT_JOINS}
     WHERE a.tenant_id = CAST(:tenant AS uuid)
     ORDER BY a.as_of DESC, a.recorded_at DESC, a.event_id
     LIMIT :limit
    """
)

_ALERT_DETAIL = text(
    f"""
    SELECT {_ALERT_COLUMNS}
    {_ALERT_JOINS}
     WHERE a.tenant_id = CAST(:tenant AS uuid)
       AND a.event_id = CAST(:event AS uuid)
    """
)

# THE HISTORY, and what it can honestly be. Rows sharing (declaration_id, target) at other slots:
# the idempotency index is (declaration_id, declaration_version, verb, as_of, target,
# payload_hash), so a repeat of the SAME slot with the SAME payload writes NOTHING and is
# invisible here by construction. A gap therefore means "not re-raised", never "resolved" — the
# page says so rather than letting a reader infer the wrong one.
#
# KEYED ON event_id, NOT as_of. payload_hash is part of that index, so one slot can legitimately
# hold two rows if the payload changed within it; collapsing on as_of would hide the second.
#
# MATCHED ON THE WHOLE `target`, not on store_id/sku_id, because target IS the grain the
# idempotency index uses. An analysis at a different grain would group correctly without a change
# here.
_ALERT_HISTORY = text(
    """
    SELECT h.event_id, h.as_of, h.recorded_at, h.quantity_at_stake,
           h.days_since_last_sale, h.days_of_cover
      FROM synapse.actions h
      JOIN synapse.actions a
        ON a.tenant_id = h.tenant_id
       AND a.declaration_id = h.declaration_id
       AND a.target = h.target
     WHERE a.tenant_id = CAST(:tenant AS uuid)
       AND a.event_id = CAST(:event AS uuid)
     ORDER BY h.as_of DESC, h.recorded_at DESC
     LIMIT :limit
    """
)


@dataclass(frozen=True)
class AlertRow:
    """One recorded alert, as the tenant page lists it and the detail page headlines it.

    PLATFORM-ONLY BY CONSTRUCTION: sku_id, product_name and store_name are all in
    FORBIDDEN_TENANT_FIELDS. Never reuse this type on a tenant-facing surface.
    """

    event_id: UUID
    as_of: date
    recorded_at: datetime
    declaration_id: str
    declaration_version: str
    verb: str
    arm: str
    expires_on: date
    # AT DETECTION. The units the monitor saw when it raised this, frozen on the row.
    quantity_at_stake: Decimal | None
    days_since_last_sale: int | None
    days_of_cover: Decimal | None
    # The thresholds THIS row was judged against, not today's declaration.
    thresholds: Mapping[str, int]
    # THE GRAIN, carried so a lifecycle decision can be recorded against it. The writing
    # credential holds INSERT and no SELECT, so the target must come from a READ first.
    target: Mapping[str, Any]
    store_id: UUID | None
    sku_id: str | None
    # NULL when the mirror or canonical no longer holds the row; the alert still renders.
    store_name: str | None
    product_name: str | None
    # CURRENT. Today's stock for the same position — deliberately a different instant from
    # quantity_at_stake, and labelled as such wherever it is rendered.
    current_stock_qty: Decimal | None
    # THE LATEST OPERATOR DECISION FOR THIS TARGET, or None when nobody has acted. Per target,
    # not per event: see _LIFECYCLE_JOIN. None means untouched, which is the "open" state.
    lifecycle_verb: str | None
    lifecycle_reason: str | None
    lifecycle_snoozed_until: date | None
    lifecycle_recorded_at: datetime | None
    lifecycle_actor: str | None


@dataclass(frozen=True)
class AlertHistoryRow:
    """One earlier raising of the same alert. See _ALERT_HISTORY for what absence means."""

    event_id: UUID
    as_of: date
    recorded_at: datetime
    quantity_at_stake: Decimal | None
    days_since_last_sale: int | None
    days_of_cover: Decimal | None


@dataclass(frozen=True)
class AlertDetail:
    """One alert with its own history. ``None`` from the reader means 404, never an empty shell."""

    alert: AlertRow
    history: tuple[AlertHistoryRow, ...]


def _alert_row(row: Any) -> AlertRow:
    return AlertRow(
        event_id=_as_uuid(row["event_id"]),
        as_of=row["as_of"],
        recorded_at=row["recorded_at"],
        declaration_id=row["declaration_id"],
        declaration_version=row["declaration_version"],
        verb=row["verb"],
        arm=row["arm"],
        expires_on=row["expires_on"],
        quantity_at_stake=row["quantity_at_stake"],
        days_since_last_sale=row["days_since_last_sale"],
        days_of_cover=row["days_of_cover"],
        thresholds=row["thresholds"] or {},
        target=row["target"],
        store_id=_as_uuid(row["store_id"]) if row["store_id"] is not None else None,
        sku_id=row["sku_id"],
        store_name=row["store_name"],
        product_name=row["product_name"],
        current_stock_qty=row["current_stock_qty"],
        lifecycle_verb=row["lifecycle_verb"],
        lifecycle_reason=row["lifecycle_reason"],
        lifecycle_snoozed_until=row["lifecycle_snoozed_until"],
        lifecycle_recorded_at=row["lifecycle_recorded_at"],
        lifecycle_actor=row["lifecycle_actor"],
    )


async def tenant_alerts(
    engine: AsyncEngine, tenant_id: UUID, *, limit: int = 100
) -> tuple[AlertRow, ...] | None:
    """One tenant's recorded alerts, newest slot first. ``None`` when the tenant is unknown.

    The tenant-existence probe runs FIRST and separately, matching ``tenant_runs``: an empty list
    for a mistyped id is indistinguishable from a real tenant that has never been alerted, and
    that confusion has already cost this project once.
    """
    bounded = max(1, min(limit, _MAX_ROWS))
    async with rls_platform_session(engine, None) as conn:
        exists = (await conn.execute(_TENANT_EXISTS, {"tenant": str(tenant_id)})).first()
        if exists is None:
            return None
        rows = (
            (await conn.execute(_TENANT_ALERTS, {"tenant": str(tenant_id), "limit": bounded}))
            .mappings()
            .all()
        )
    return tuple(_alert_row(row) for row in rows)


async def alert_detail(
    engine: AsyncEngine, tenant_id: UUID, event_id: UUID, *, history_limit: int = 50
) -> AlertDetail | None:
    """One alert and its earlier raisings. ``None`` when no such alert exists FOR THIS TENANT.

    A TENANT MISMATCH IS INDISTINGUISHABLE FROM A TYPO, DELIBERATELY. Both predicates are in the
    WHERE clause, so a real event under a different tenant simply returns no row and the route
    404s. Answering 403 would confirm the event exists somewhere, which is a cross-tenant
    existence oracle on a console that spans the fleet.
    """
    async with rls_platform_session(engine, None) as conn:
        found = (
            (await conn.execute(_ALERT_DETAIL, {"tenant": str(tenant_id), "event": str(event_id)}))
            .mappings()
            .first()
        )
        if found is None:
            return None
        history = (
            (
                await conn.execute(
                    _ALERT_HISTORY,
                    {"tenant": str(tenant_id), "event": str(event_id), "limit": history_limit},
                )
            )
            .mappings()
            .all()
        )
    return AlertDetail(
        alert=_alert_row(found),
        history=tuple(
            AlertHistoryRow(
                event_id=_as_uuid(row["event_id"]),
                as_of=row["as_of"],
                recorded_at=row["recorded_at"],
                quantity_at_stake=row["quantity_at_stake"],
                days_since_last_sale=row["days_since_last_sale"],
                days_of_cover=row["days_of_cover"],
            )
            for row in history
        ),
    )
