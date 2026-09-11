"""Wire shapes + the read-side status derivation for Connector Health (GET /connector-health).

One endpoint consumes this: ``GET /connector-health`` — the tenant's connectors (one row per
``config.sources`` entry), each carrying worker-produced liveness/freshness telemetry
(``telemetry.connector_health``, D116) coalesced with the bronze last-arrival.

The DISPLAYED ``status`` is DERIVED ON READ here (``derive_status``), NOT the worker's stored
coarse hint: the worker stamps ``healthy``/``stale`` as facts, but the surface classifies from
the effective signals — auth-expiry proximity, rate-limit presence, freshness age — and falls
back to ``pending`` where there is no producer and no activity (the 3 deferred receivers, and any
registered-but-idle source). This mirrors the ``runs`` crosswalk-in-schema / call-from-handler
split: the repo speaks DB vocabulary, the wire translation lives here.

Cadence is a DISPLAY label only (``heartbeat_label`` from ``config.sources.schedule``); Phase A
does not machine-compute it, so ``missed_intervals`` is worker-emitted-or-null and there is no
precise missed-interval math.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel

# Wire vocabularies (DB never leaks; the UI sees these only).
ChannelWire = Literal["csv_upload", "api", "csv_erp", "reverse_api"]
# The displayed status set (derived on read). Superset of the worker's coarse hint
# (healthy/stale) with the read-derived auth_expiring / rate_limited / pending.
StatusWire = Literal["healthy", "stale", "auth_expiring", "rate_limited", "pending"]

# Coarse Phase-A thresholds (documented as coarse — cadence is not machine-computed yet, D116).
# A connector not seen within this window reads stale; auth within this window reads auth_expiring.
STALE_AFTER = timedelta(hours=24)
AUTH_EXPIRING_WITHIN = timedelta(days=7)


def derive_status(
    *,
    effective_last_seen: datetime | None,
    auth_expires_at: datetime | None,
    rate_limit_state: str | None,
    now: datetime,
) -> StatusWire:
    """Classify the displayed connector status from the effective signals.

    Precedence (most-actionable first): auth expiring soon > rate-limited > no activity
    (pending) > stale (seen, but not recently) > healthy. ``effective_last_seen`` is the
    COALESCE of the worker's ``last_seen_at`` and the bronze ``MAX(received_at)``, so an active
    connector reads healthy even before the worker has ever emitted a health row.
    """
    if auth_expires_at is not None and auth_expires_at <= now + AUTH_EXPIRING_WITHIN:
        return "auth_expiring"
    if rate_limit_state is not None:
        return "rate_limited"
    if effective_last_seen is None:
        # No producer and no activity — the 3 deferred receivers, or a registered-but-idle source.
        return "pending"
    if now - effective_last_seen > STALE_AFTER:
        return "stale"
    return "healthy"


class ConnectorHealthRow(BaseModel):
    """One connector's health (per ``config.sources`` entry).

    ``last_seen_at`` is the COALESCE of worker telemetry and the bronze last-arrival.
    ``heartbeat_label`` is the human cadence from ``config.sources.schedule`` (display only —
    Phase A does not machine-compute cadence, so ``missed_intervals`` is null unless a worker
    emitted it). Timestamps are ISO-8601, UTC as ``Z``.
    """

    tenant_id: str  # the owning tenant (config.sources.tenant_id, NOT NULL) — fleet attribution (Chunk 1)
    tenant_name: str | None  # identity_mirror.tenants.name; null when tenant unmirrored (Chunk 9)
    source_id: str
    display_name: str
    channel: ChannelWire | None  # nullable in config.sources (unknown channel)
    heartbeat_label: str | None  # config.sources.schedule, display cadence
    status: StatusWire  # DERIVED ON READ (derive_status)
    last_seen_at: str | None  # COALESCE(health.last_seen_at, bronze MAX(received_at))
    last_error_at: str | None
    last_error_detail: str | None
    auth_expires_at: str | None
    rate_limit_state: str | None
    missed_intervals: int | None  # worker-emitted-or-null (no machine cadence in Phase A)


class ConnectorHealthListResponse(BaseModel):
    """The list body: the tenant's connectors with health (bounded newest-first, no paging)."""

    items: list[ConnectorHealthRow]
