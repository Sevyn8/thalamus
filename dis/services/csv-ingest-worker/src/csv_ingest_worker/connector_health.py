"""The connector-health emit: one idempotent per-run upsert of liveness/freshness.

Mirrors ``bronze.py`` EXACTLY: every statement runs on a connection yielded by
``dis-rls`` ``rls_session`` under the EVENT's tenant — tenant
scoping is the RLS policy's (``telemetry.connector_health`` is FORCE RLS,
``tenant_isolation`` USING + WITH CHECK on ``app.tenant_id``), inherited target guard
included (``current_database()=='ithina_dis_db'``, NOBYPASSRLS; DIS on 5433, never CM).
The WITH CHECK is the structural backstop: a worker can only stamp health for its own
event's tenant (the write-isolation test proves this).

This is the WORKER side of the producer/consumer split (the inverse of config.sources,
which is BFF-written). It writes the FACTS the surface reads:
  - a successful arrival stamps ``last_seen_at = now`` and the coarse ``status = 'healthy'``;
  - a failed run stamps ``last_error_at = now`` + ``last_error_detail`` and ``status = 'stale'``.
The BFF derives the DISPLAYED status on read (freshness / auth / rate-limit), so this coarse
worker status is only a hint; the columns not set by a given path keep their prior value
(the upsert never nulls a column it is not stamping).

ADDITIVE + FIRE-AND-FORGET at the call site: the pipeline calls this AFTER its bronze write
and never lets a health-emit failure touch the data path (the same posture as
fire-and-forget audit telemetry). The upsert itself raises on an RLS
violation — the swallow lives only in the pipeline caller, so the write-isolation test can
assert WITH CHECK by calling this directly.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from dis_core.timestamps import now_utc

# The coarse worker status hints (a subset of the DDL CHECK vocab; the BFF read derives
# auth_expiring / rate_limited / pending). Kept here so the emit and its tests share one source.
STATUS_HEALTHY = "healthy"
STATUS_STALE = "stale"


async def upsert_health_seen(conn: AsyncConnection, *, tenant_id: UUID, source_id: str) -> None:
    """A successful arrival: stamp ``last_seen_at = now`` + ``status = 'healthy'`` (idempotent).

    ON CONFLICT keeps every column this path does not stamp (error fields, auth, rate-limit),
    so a healthy re-run never clears a prior error record — it only refreshes freshness.
    RLS WITH CHECK enforces the tenant (``conn`` must come from ``rls_session`` under it).
    """
    await conn.execute(
        text(
            "INSERT INTO telemetry.connector_health "
            "(tenant_id, source_id, last_seen_at, status, updated_at) "
            "VALUES (:tenant_id, :source_id, :now, :status, :now) "
            "ON CONFLICT (tenant_id, source_id) DO UPDATE SET "
            "last_seen_at = EXCLUDED.last_seen_at, "
            "status = EXCLUDED.status, "
            "updated_at = EXCLUDED.updated_at"
        ),
        {
            "tenant_id": tenant_id,
            "source_id": source_id,
            "now": now_utc(),
            "status": STATUS_HEALTHY,
        },
    )


async def upsert_health_error(conn: AsyncConnection, *, tenant_id: UUID, source_id: str, detail: str) -> None:
    """A failed run: stamp ``last_error_at = now`` + ``last_error_detail`` + ``status = 'stale'``.

    Keeps ``last_seen_at`` (a prior success stays visible) — the upsert stamps only the error
    fields + the coarse status. ``detail`` is a coarse, non-PII reason code (never payload).
    RLS WITH CHECK enforces the tenant.
    """
    await conn.execute(
        text(
            "INSERT INTO telemetry.connector_health "
            "(tenant_id, source_id, last_error_at, last_error_detail, status, updated_at) "
            "VALUES (:tenant_id, :source_id, :now, :detail, :status, :now) "
            "ON CONFLICT (tenant_id, source_id) DO UPDATE SET "
            "last_error_at = EXCLUDED.last_error_at, "
            "last_error_detail = EXCLUDED.last_error_detail, "
            "status = EXCLUDED.status, "
            "updated_at = EXCLUDED.updated_at"
        ),
        {
            "tenant_id": tenant_id,
            "source_id": source_id,
            "now": now_utc(),
            "detail": detail,
            "status": STATUS_STALE,
        },
    )
