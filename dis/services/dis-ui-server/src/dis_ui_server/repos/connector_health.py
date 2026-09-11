"""``telemetry.connector_health`` reads — the Connector Health data access (GET /connector-health).

READ-ONLY: dis-ui-server READS this table; ``csv-ingest-worker`` (and, later, the other
receivers) remain its SOLE writers. This module builds SELECT-only statements — never an
INSERT/UPDATE/DELETE (the inverse of ``config.sources``, which the BFF writes).

The read drives FROM ``config.sources`` (the connector registry, so every registered source
appears) LEFT JOIN ``telemetry.connector_health`` (the worker telemetry, absent → pending) LEFT
JOIN a bronze ``MAX(received_at)`` per-source subquery. ``last_seen_at`` is COALESCE(health,
bronze) so an active connector shows real freshness even before the worker has emitted a health
row. All three tables are two-GUC RLS (USING tenant OR PLATFORM), so
per-tenant scope is the DATABASE's guarantee under ``read_session``; the explicit ``WHERE
s.tenant_id`` predicate (pinned scope only) is defense-in-depth, mirroring ``repos/runs.py`` /
``repos/canonical.py``.

Reads execute on the ``read_session`` connection; never an
``AsyncSession``, never a ``.commit()``. This module speaks DB vocabulary only — the wire status
derivation + ISO rendering live in the handler (mirroring ``runs``). Rows are ordered by
``source_id`` (a bounded per-tenant registry; no pagination this slice).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_ui_server.auth.scope import ReadScope
from dis_ui_server.db import read_session

# The read: config.sources (driving) LEFT JOIN connector_health (telemetry) LEFT JOIN a bronze
# per-source last-arrival. COALESCE happens in the handler (raw columns here). The tenant
# predicate is appended for a pinned (TENANT) scope only — PLATFORM see-all is the RLS USING
# branch, and re-pinning would break the widened read (same rule as repos/runs.py _tenant_term).
_SELECT = (
    "SELECT "
    "  s.tenant_id                AS tenant_id, "  # projected for fleet attribution (Chunk 1)
    "  t.name                     AS tenant_name, "  # LEFT JOIN identity_mirror.tenants (Chunk 9)
    "  s.source_id                AS source_id, "
    "  s.display_name             AS display_name, "
    "  s.channel                  AS channel, "
    "  s.schedule                 AS heartbeat_label, "
    "  h.last_seen_at             AS health_last_seen_at, "
    "  h.last_error_at            AS last_error_at, "
    "  h.last_error_detail        AS last_error_detail, "
    "  h.auth_expires_at          AS auth_expires_at, "
    "  h.rate_limit_state         AS rate_limit_state, "
    "  h.missed_intervals         AS missed_intervals, "
    "  b.bronze_last_seen         AS bronze_last_seen "
    "FROM config.sources s "
    # LEFT JOIN identity_mirror.tenants for tenant_name (Chunk 9). Keyed on the tenant PK (≤1
    # match, no fan-out); RLS-OFF table, read under the existing read_session.
    "LEFT JOIN identity_mirror.tenants t "
    "       ON t.tenant_id = s.tenant_id "
    "LEFT JOIN telemetry.connector_health h "
    "       ON h.tenant_id = s.tenant_id AND h.source_id = s.source_id "
    "LEFT JOIN ( "
    "    SELECT tenant_id, source_id, MAX(received_at) AS bronze_last_seen "
    "    FROM bronze.data_ingress_events "
    "    GROUP BY tenant_id, source_id "
    ") b ON b.tenant_id = s.tenant_id AND b.source_id = s.source_id "
)

_ORDER = " ORDER BY s.source_id"


async def list_connector_health(engine: AsyncEngine, scope: ReadScope) -> Sequence[Row[Any]]:
    """The tenant's connectors with health (ordered by source_id).

    TENANT sees its own (RLS + the defense-in-depth predicate); PLATFORM see-all reads across
    every tenant via the policy USING branch (no in-query re-pin). ``scope`` comes from
    ``require_read_scope`` (verified token only).
    """
    params: dict[str, Any] = {}
    where = ""
    if not scope.is_platform:
        # Pinned TENANT scope always carries a UUID (the catastrophe invariant); defense-in-depth
        # on the driving table on top of the RLS policy.
        where = " WHERE s.tenant_id = :tenant_id"
        params["tenant_id"] = scope.tenant_id
    statement = text(_SELECT + where + _ORDER)
    async with read_session(engine, is_platform=scope.is_platform, tenant_id=scope.tenant_id) as conn:
        return list((await conn.execute(statement, params)).all())


__all__ = ["list_connector_health"]
