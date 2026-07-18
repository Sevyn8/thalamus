"""Dashboard metric reads - pure tenant-scoped SELECTs over existing tables.

Every statement runs inside ONE ``rls_session(engine, tenant_id)`` so the per-tenant
GUC (``app.tenant_id``) scopes the audit / quarantine / canonical reads exactly like
the other tenant-facing read repos (mapping-templates, stores). Read-only: no writes,
no DDL, no business logic beyond aggregation. Canonical reads go through the dis-rls
helper (hard rule 1).

Sources:
- ``audit.events`` RECEIVED/SUCCESS rows carry the upload's ``row_count`` (the CSV
  upload receiver emits one per accepted upload) and ``event_data->>'template_id'``.
- ``quarantine.quarantined_rows`` / ``quarantined_chunks`` carry ``quarantined_at``.
- ``canonical.*`` are the mapping-produced ingest tables (signal_history is derived
  daily-compute output, NOT ingested records, so it is excluded from the count).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_ui_server.auth.scope import ReadScope
from dis_ui_server.db import read_session

# The canonical tables that hold mapping-produced ingest rows. store_sku_signal_history
# is daily-compute DERIVED output (not ingested records), so it is deliberately excluded.
# Static literals (no user input) - safe to interpolate into the count statement.
_CANONICAL_TABLES: tuple[str, ...] = (
    "store_sku_current_position",
    "store_sku_sale_events",
    "store_sku_change_events",
)

# COUNT(*) on the append-only event tables is acceptable at beta scale (~150K/day); a
# cached/approximate count is a later optimization if these grow large.

_ROWS_INGESTED_24H = text(
    "SELECT COALESCE(SUM(row_count), 0) AS n FROM audit.events "
    "WHERE stage = 'RECEIVED' AND outcome = 'SUCCESS' "
    "AND event_timestamp >= now() - interval '24 hours'"
)

_QUARANTINED_24H = text(
    "SELECT "
    "(SELECT count(*) FROM quarantine.quarantined_rows "
    " WHERE quarantined_at >= now() - interval '24 hours') "
    "+ "
    "(SELECT count(*) FROM quarantine.quarantined_chunks "
    " WHERE quarantined_at >= now() - interval '24 hours') AS n"
)

_FLOW_24H = text(
    "SELECT event_data->>'template_id' AS template_id, "
    "COALESCE(SUM(row_count), 0) AS rows_24h, "
    "MAX(event_timestamp) AS last_received_at "
    "FROM audit.events "
    "WHERE stage = 'RECEIVED' AND outcome = 'SUCCESS' "
    "AND event_timestamp >= now() - interval '24 hours' "
    "GROUP BY 1 ORDER BY rows_24h DESC"
)

# "Sources connected" KPI: the count of DISTINCT sources the tenant has a mapping for (any
# status — a source is connected once it has a mapping in config.source_mappings). RLS-scoped
# via the session GUC exactly like the aggregates above (config.source_mappings is two-GUC RLS,
# in the read-set). No in-query tenant predicate — the policy is the scope.
_SOURCES_CONNECTED = text("SELECT count(DISTINCT source_id) AS n FROM config.source_mappings")

# Per-tenant breakdown (Chunk 6, PLATFORM-only): the SAME source data + window as the fleet
# aggregates above, GROUP BY tenant_id. No in-query tenant predicate — the PLATFORM see-all scope
# (policy USING branch) exposes every tenant; the GROUP BY partitions the identical rows, so the
# fleet aggregate == the sum across the breakdown. ``tenant_id IS NOT NULL`` drops non-tenant
# system rows (uploads are always tenant-scoped, so this never affects the RECEIVED reconcile).
#
# Chunk 9 adds a LEFT JOIN identity_mirror.tenants for tenant_name. Grouping additionally by
# ``t.name`` does NOT change the aggregate values: name is functionally dependent on tenant_id (its
# PK), so ``(tenant_id, name)`` is the SAME partition as ``tenant_id`` — the SUM/count are
# byte-identical to Chunk 6. RLS-OFF table (D41); LEFT so an unmirrored tenant → NULL name.
_ROWS_INGESTED_BY_TENANT = text(
    "SELECT e.tenant_id AS tenant_id, COALESCE(SUM(e.row_count), 0) AS n, t.name AS tenant_name "
    "FROM audit.events e "
    "LEFT JOIN identity_mirror.tenants t ON t.tenant_id = e.tenant_id "
    "WHERE e.stage = 'RECEIVED' AND e.outcome = 'SUCCESS' "
    "AND e.event_timestamp >= now() - interval '24 hours' "
    "AND e.tenant_id IS NOT NULL "
    "GROUP BY e.tenant_id, t.name"
)

_QUARANTINED_BY_TENANT = text(
    "SELECT q.tenant_id AS tenant_id, count(*) AS n, t.name AS tenant_name FROM ("
    "  SELECT tenant_id FROM quarantine.quarantined_rows "
    "   WHERE quarantined_at >= now() - interval '24 hours' "
    "  UNION ALL "
    "  SELECT tenant_id FROM quarantine.quarantined_chunks "
    "   WHERE quarantined_at >= now() - interval '24 hours' "
    ") q "
    "LEFT JOIN identity_mirror.tenants t ON t.tenant_id = q.tenant_id "
    "GROUP BY q.tenant_id, t.name"
)


@dataclass(frozen=True)
class FlowAggRow:
    """One template's 24h ingest aggregate (raw, pre-wire)."""

    template_id: str | None
    rows_24h: int
    last_received_at: datetime | None


@dataclass(frozen=True)
class TenantAggRow:
    """One tenant's 24h core aggregates (raw, pre-wire) — the PLATFORM breakdown (Chunk 6)."""

    tenant_id: str
    rows_ingested_24h: int
    quarantined_rows_24h: int
    tenant_name: str | None  # identity_mirror.tenants.name; null when unmirrored (Chunk 9)


@dataclass(frozen=True)
class DashboardMetricsData:
    """The raw metric values read from the DB; the handler maps these to the wire."""

    rows_ingested_24h: int
    quarantined_rows_24h: int
    canonical_by_table: list[tuple[str, int]]
    flow: list[FlowAggRow]
    sources_connected: int
    # PLATFORM-only per-tenant breakdown; empty for a TENANT scope (Chunk 6).
    by_tenant: list[TenantAggRow]


async def fetch_dashboard_metrics(engine: AsyncEngine, scope: ReadScope) -> DashboardMetricsData:
    """Read every Dashboard metric in one scoped session (Slice 17b).

    ``scope`` comes from ``require_read_scope`` (verified token only): a TENANT scope
    pins ``app.tenant_id``; a PLATFORM scope reads see-all (aggregates span every tenant)
    via the policy USING branch. All reads are scoped by RLS — no in-query predicate.
    """
    async with read_session(engine, is_platform=scope.is_platform, tenant_id=scope.tenant_id) as conn:
        rows_ingested = int((await conn.execute(_ROWS_INGESTED_24H)).scalar_one())
        quarantined = int((await conn.execute(_QUARANTINED_24H)).scalar_one())
        sources_connected = int((await conn.execute(_SOURCES_CONNECTED)).scalar_one())

        canonical_by_table: list[tuple[str, int]] = []
        for table in _CANONICAL_TABLES:
            count = int(
                (await conn.execute(text(f"SELECT count(*) AS n FROM canonical.{table}"))).scalar_one()
            )
            canonical_by_table.append((table, count))

        flow = [
            FlowAggRow(
                template_id=row.template_id,
                rows_24h=int(row.rows_24h),
                last_received_at=row.last_received_at,
            )
            for row in (await conn.execute(_FLOW_24H)).all()
        ]

        # Per-tenant breakdown: PLATFORM see-all only. For a TENANT scope the aggregate IS the
        # tenant's own numbers, so a breakdown would just duplicate it — left empty. Same session,
        # same window, GROUP BY tenant_id; merged by tenant_id so each entry reconciles with the
        # fleet aggregate (sum of by_tenant == the aggregate).
        by_tenant: list[TenantAggRow] = []
        if scope.is_platform:
            received_rows = (await conn.execute(_ROWS_INGESTED_BY_TENANT)).all()
            quarantined_rows = (await conn.execute(_QUARANTINED_BY_TENANT)).all()
            received_by_tenant = {str(row.tenant_id): int(row.n) for row in received_rows}
            quarantined_by_tenant = {
                str(row.tenant_id): int(row.n) for row in quarantined_rows if row.tenant_id is not None
            }
            # tenant_name from either query (Chunk 9): both carry the LEFT-joined name for the same
            # tenant, so build the map from received first, then fill any quarantine-only tenants.
            name_by_tenant: dict[str, str | None] = {}
            for row in received_rows:
                name_by_tenant[str(row.tenant_id)] = row.tenant_name
            for row in quarantined_rows:
                if row.tenant_id is not None:
                    name_by_tenant.setdefault(str(row.tenant_id), row.tenant_name)
            for tenant_id in sorted(received_by_tenant.keys() | quarantined_by_tenant.keys()):
                by_tenant.append(
                    TenantAggRow(
                        tenant_id=tenant_id,
                        rows_ingested_24h=received_by_tenant.get(tenant_id, 0),
                        quarantined_rows_24h=quarantined_by_tenant.get(tenant_id, 0),
                        tenant_name=name_by_tenant.get(tenant_id),
                    )
                )

    return DashboardMetricsData(
        rows_ingested_24h=rows_ingested,
        quarantined_rows_24h=quarantined,
        canonical_by_table=canonical_by_table,
        flow=flow,
        sources_connected=sources_connected,
        by_tenant=by_tenant,
    )
