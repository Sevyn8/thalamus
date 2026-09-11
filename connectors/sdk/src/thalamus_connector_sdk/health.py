"""Connector-health emit with an optional metadata hint and the rate-limit posture.

Mirrors csv-ingest-worker's ``connector_health`` upserts (same table, same
``ON CONFLICT (tenant_id, source_id)`` semantics, same "never null a column this path is
not stamping" rule) but adds two columns the CSV worker's variant does not carry: an
optional ``metadata`` JSONB — e.g. ``{"dropped_count": N}`` — and ``rate_limit_state``.
Kept in the SDK so the connector owns its health-write shape without changing the CSV
worker (nothing here is imported by, or imports, ``csv_ingest_worker.connector_health``).

TWO MERGE DISCIPLINES, because the two columns mean different things:

- ``metadata`` is an accumulating HINT: merged with ``COALESCE(EXCLUDED.metadata, ...)``,
  so passing ``None`` preserves any prior value.
- ``rate_limit_state`` is a current POSTURE, and the read side (dis-ui-server
  ``derive_status``) reads ANY non-null as ``rate_limited``. A COALESCE would therefore
  LATCH the first observed throttle forever. So the column distinguishes two callers:
  one that KNOWS the posture (it extracted; ``None`` is its positive "no rate-limit
  response this run", and it clears a stored value) from one that does not (a duplicate
  no-op never extracted). The ignorant caller passes :data:`RATE_LIMIT_UNKNOWN` and the
  ``CASE WHEN :stamp_rate_limit`` preserves whatever is stored. Only genuine ignorance
  earns preservation; an authoritative ``None`` is a write.

Every statement runs on a ``dis-rls`` ``rls_session`` connection under the trigger's
tenant (hard rules 1 & 12); the WITH CHECK pins the write to that tenant. The caller keeps
the fire-and-forget posture (a health-emit failure never blocks ingest).
"""

from __future__ import annotations

import json
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from dis_core.timestamps import now_utc

STATUS_HEALTHY = "healthy"
STATUS_STALE = "stale"


class _RateLimitUnknown:
    """The type of :data:`RATE_LIMIT_UNKNOWN`; a third state beside ``str`` and ``None``."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "RATE_LIMIT_UNKNOWN"


#: This emit does not know the rate-limit posture — preserve whatever is stored. Distinct
#: from ``None``, which asserts "no rate-limit response observed" and CLEARS the column.
RATE_LIMIT_UNKNOWN: Final = _RateLimitUnknown()

# What a caller may pass for the posture: a vocabulary value, an authoritative None, or
# the ignorance sentinel.
type RateLimitState = str | None | _RateLimitUnknown

# The DO UPDATE fragment for the posture. `:stamp_rate_limit` is False only for the
# ignorance sentinel, in which case the stored value survives untouched. The bind is CAST
# explicitly, matching CAST(:metadata AS JSONB) in the same statement: psycopg3 would very
# probably infer boolean from the CASE WHEN position, but the cast makes the parameter type
# a property of the statement rather than of driver inference.
_RATE_LIMIT_MERGE = (
    "rate_limit_state = CASE WHEN CAST(:stamp_rate_limit AS BOOLEAN) "
    "THEN EXCLUDED.rate_limit_state "
    "ELSE telemetry.connector_health.rate_limit_state END, "
)


def _metadata_json(metadata: dict[str, Any] | None) -> str | None:
    """Serialize the metadata dict for the ``CAST(:metadata AS JSONB)`` bind, or None."""
    return json.dumps(metadata) if metadata is not None else None


def _rate_limit_binds(state: RateLimitState) -> dict[str, Any]:
    """The (stamp?, value) bind pair for the posture. Ignorance stamps nothing."""
    if isinstance(state, _RateLimitUnknown):
        return {"stamp_rate_limit": False, "rate_limit_state": None}
    return {"stamp_rate_limit": True, "rate_limit_state": state}


async def upsert_health_seen(
    conn: AsyncConnection,
    *,
    tenant_id: UUID,
    source_id: str,
    metadata: dict[str, Any] | None = None,
    rate_limit_state: RateLimitState = RATE_LIMIT_UNKNOWN,
) -> None:
    """A successful arrival: stamp ``last_seen_at`` + ``status='healthy'`` (idempotent).

    ``metadata`` (e.g. ``{"dropped_count": N}``) is merged, not overwritten: a None keeps
    the stored value via COALESCE, so a healthy re-run never clears a prior hint.

    ``rate_limit_state`` defaults to :data:`RATE_LIMIT_UNKNOWN` (preserve) because the
    duplicate no-op paths never extracted and cannot know. A caller that DID extract
    passes the posture it observed — including an explicit ``None``, which clears a
    previously stored throttle.
    """
    await conn.execute(
        text(
            "INSERT INTO telemetry.connector_health "
            "(tenant_id, source_id, last_seen_at, status, rate_limit_state, metadata, updated_at) "
            "VALUES (:tenant_id, :source_id, :now, :status, :rate_limit_state, "
            "CAST(:metadata AS JSONB), :now) "
            "ON CONFLICT (tenant_id, source_id) DO UPDATE SET "
            "last_seen_at = EXCLUDED.last_seen_at, "
            "status = EXCLUDED.status, " + _RATE_LIMIT_MERGE + "metadata = COALESCE(EXCLUDED.metadata, "
            "telemetry.connector_health.metadata), "
            "updated_at = EXCLUDED.updated_at"
        ),
        {
            "tenant_id": tenant_id,
            "source_id": source_id,
            "now": now_utc(),
            "status": STATUS_HEALTHY,
            "metadata": _metadata_json(metadata),
            **_rate_limit_binds(rate_limit_state),
        },
    )


async def upsert_health_error(
    conn: AsyncConnection,
    *,
    tenant_id: UUID,
    source_id: str,
    detail: str,
    metadata: dict[str, Any] | None = None,
    rate_limit_state: RateLimitState = RATE_LIMIT_UNKNOWN,
) -> None:
    """A failed run: stamp ``last_error_at`` + ``last_error_detail`` + ``status='stale'``.

    Keeps ``last_seen_at`` (a prior success stays visible); ``detail`` is a coarse non-PII
    reason code (never payload). ``metadata`` follows the same COALESCE-merge rule.

    ``rate_limit_state`` defaults to :data:`RATE_LIMIT_UNKNOWN`: a failure for some OTHER
    cause says nothing about throttling and must not clear a stored posture. Only the
    rate-limit failure itself passes a value.
    """
    await conn.execute(
        text(
            "INSERT INTO telemetry.connector_health "
            "(tenant_id, source_id, last_error_at, last_error_detail, status, rate_limit_state, "
            "metadata, updated_at) "
            "VALUES (:tenant_id, :source_id, :now, :detail, :status, :rate_limit_state, "
            "CAST(:metadata AS JSONB), :now) "
            "ON CONFLICT (tenant_id, source_id) DO UPDATE SET "
            "last_error_at = EXCLUDED.last_error_at, "
            "last_error_detail = EXCLUDED.last_error_detail, "
            "status = EXCLUDED.status, " + _RATE_LIMIT_MERGE + "metadata = COALESCE(EXCLUDED.metadata, "
            "telemetry.connector_health.metadata), "
            "updated_at = EXCLUDED.updated_at"
        ),
        {
            "tenant_id": tenant_id,
            "source_id": source_id,
            "now": now_utc(),
            "detail": detail,
            "status": STATUS_STALE,
            "metadata": _metadata_json(metadata),
            **_rate_limit_binds(rate_limit_state),
        },
    )
