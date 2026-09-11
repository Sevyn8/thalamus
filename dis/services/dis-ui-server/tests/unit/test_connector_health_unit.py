"""Unit tests for Connector Health (GET /connector-health).

Two halves. PURE: the read-side status derivation (``derive_status`` precedence + freshness
threshold), and the handler's row->wire mapper (the last_seen COALESCE of worker telemetry with
the bronze last-arrival, ISO rendering, channel/heartbeat passthrough, derived status, nulls).
WIRE: the parts that resolve before / around the DB call — auth/scope (401/403) — and, with the
repo monkeypatched to fixed rows, the handler's mapping to the wire (incl. the pending fallback
when a connector has neither a health row nor bronze activity). DB-backed behaviour (isolation,
coalesce over real rows) is the integration suite's job.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from dis_core.timestamps import now_utc
from dis_ui_server.handlers.connector_health import _iso, _to_row
from dis_ui_server.schemas.connector_health import (
    AUTH_EXPIRING_WITHIN,
    STALE_AFTER,
    derive_status,
)

TENANT_A = "019e5e3c-b5d3-705f-9002-2451c4ca2626"  # buc-ees

_NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _fake_row(**overrides: Any) -> Any:
    """A stand-in for the repo's Row over the connector_health SELECT (attribute access)."""
    base: dict[str, Any] = {
        "tenant_id": "0190ac0e-1a01-7001-8a01-0000000000dd",
        "tenant_name": "Buc-ees",  # Chunk 9: identity_mirror.tenants.name (LEFT JOIN)
        "source_id": "manual_csv_upload",
        "display_name": "Manual Csv Upload",
        "channel": "csv_upload",
        "heartbeat_label": "every 15 min",
        "health_last_seen_at": datetime(2026, 7, 13, 11, 55, 0, tzinfo=UTC),
        "last_error_at": None,
        "last_error_detail": None,
        "auth_expires_at": None,
        "rate_limit_state": None,
        "missed_intervals": None,
        "bronze_last_seen": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# -- PURE: derive_status precedence + freshness threshold ----------------------------


def test_derive_healthy_when_recently_seen() -> None:
    assert (
        derive_status(
            effective_last_seen=_NOW - timedelta(minutes=5),
            auth_expires_at=None,
            rate_limit_state=None,
            now=_NOW,
        )
        == "healthy"
    )


def test_derive_stale_when_seen_beyond_threshold() -> None:
    assert (
        derive_status(
            effective_last_seen=_NOW - STALE_AFTER - timedelta(minutes=1),
            auth_expires_at=None,
            rate_limit_state=None,
            now=_NOW,
        )
        == "stale"
    )


def test_derive_pending_when_never_seen() -> None:
    # No producer and no activity — the 3 deferred receivers, or a registered-but-idle source.
    assert (
        derive_status(effective_last_seen=None, auth_expires_at=None, rate_limit_state=None, now=_NOW)
        == "pending"
    )


def test_derive_auth_expiring_takes_precedence_over_freshness() -> None:
    # Even a freshly-seen connector reads auth_expiring if its credential expires within the window.
    assert (
        derive_status(
            effective_last_seen=_NOW,
            auth_expires_at=_NOW + AUTH_EXPIRING_WITHIN - timedelta(hours=1),
            rate_limit_state=None,
            now=_NOW,
        )
        == "auth_expiring"
    )


def test_derive_rate_limited_when_state_present() -> None:
    assert (
        derive_status(
            effective_last_seen=_NOW,
            auth_expires_at=None,
            rate_limit_state="throttled",
            now=_NOW,
        )
        == "rate_limited"
    )


def test_derive_auth_expiring_outranks_rate_limited() -> None:
    assert (
        derive_status(
            effective_last_seen=_NOW,
            auth_expires_at=_NOW + timedelta(hours=1),
            rate_limit_state="throttled",
            now=_NOW,
        )
        == "auth_expiring"
    )


def test_iso_renders_utc_as_z_and_passes_none() -> None:
    assert _iso(datetime(2026, 6, 3, 9, 8, 0, tzinfo=UTC)) == "2026-06-03T09:08:00Z"
    assert _iso(None) is None


# -- PURE: the row -> wire mapper (COALESCE, ISO, derived status, nulls) --------------


def test_to_row_prefers_worker_last_seen() -> None:
    wire = _to_row(
        _fake_row(
            health_last_seen_at=datetime(2026, 7, 13, 11, 59, 0, tzinfo=UTC),
            bronze_last_seen=datetime(2020, 1, 1, tzinfo=UTC),
        ),
        now=_NOW,
    )
    assert wire.last_seen_at == "2026-07-13T11:59:00Z"  # worker value wins the COALESCE
    assert wire.status == "healthy"
    assert wire.channel == "csv_upload"
    assert wire.heartbeat_label == "every 15 min"


def test_to_row_coalesces_bronze_when_no_health_row() -> None:
    # The required coalesce: a source with bronze activity but NO health row still shows
    # a real last_seen (from bronze MAX(received_at)) and reads healthy/stale off it.
    wire = _to_row(
        _fake_row(
            health_last_seen_at=None,
            bronze_last_seen=_NOW - timedelta(minutes=10),
        ),
        now=_NOW,
    )
    assert wire.last_seen_at == _iso(_NOW - timedelta(minutes=10))
    assert wire.status == "healthy"


def test_to_row_pending_when_neither_health_nor_bronze() -> None:
    wire = _to_row(_fake_row(health_last_seen_at=None, bronze_last_seen=None), now=_NOW)
    assert wire.last_seen_at is None
    assert wire.status == "pending"


def test_to_row_null_channel_passes_through() -> None:
    wire = _to_row(_fake_row(channel=None, heartbeat_label=None), now=_NOW)
    assert wire.channel is None
    assert wire.heartbeat_label is None


# -- WIRE: behaviour that resolves before / around the DB call -----------------------


def test_list_requires_a_token(client: TestClient) -> None:
    response = client.get("/api/v1/connector-health")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_token"


def test_list_denies_platform_without_ops(client: TestClient, mint_token: Callable[..., str]) -> None:
    token = mint_token(user_type="PLATFORM", tenant_id=None, roles=("dis:read",))
    response = client.get("/api/v1/connector-health", headers=_bearer(token))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ops_role_required"


def test_list_maps_repo_rows_to_wire(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: Any
) -> None:
    row = _fake_row(
        health_last_seen_at=None,
        bronze_last_seen=now_utc() - timedelta(minutes=2),  # active via bronze, no health row
    )

    async def _fake_list(*_args: Any, **_kwargs: Any) -> list[Any]:
        return [row]

    monkeypatch.setattr("dis_ui_server.handlers.connector_health.list_connector_health", _fake_list)
    resp = client.get("/api/v1/connector-health", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["source_id"] == "manual_csv_upload"
    assert item["status"] == "healthy"  # coalesced from bronze
    assert item["last_seen_at"] is not None
    assert item["heartbeat_label"] == "every 15 min"


def test_to_row_projects_tenant_id_and_attributes_cross_tenant() -> None:
    # Chunk 1: connector row carries its owning tenant (config.sources.tenant_id, NOT NULL).
    a = _to_row(_fake_row(tenant_id="0190ac0e-1a01-7001-8a01-0000000000dd"), now=_NOW)
    assert a.tenant_id == "0190ac0e-1a01-7001-8a01-0000000000dd"
    b = _to_row(_fake_row(tenant_id="0190ac0e-1a01-7001-8a01-0000000000ee"), now=_NOW)
    assert a.tenant_id != b.tenant_id
    # Chunk 9: tenant_name maps through; LEFT-JOIN-null (unmirrored tenant) → null, row still returned.
    assert a.tenant_name == "Buc-ees"
    assert _to_row(_fake_row(tenant_name=None), now=_NOW).tenant_name is None
