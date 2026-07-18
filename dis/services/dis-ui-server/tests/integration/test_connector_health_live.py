"""``GET /connector-health`` against the LIVE stack (D116) — read isolation, coalesce, derivation.

Proves the BFF READ over the worker-written table: a TENANT sees only its own connectors and a
PLATFORM+ops actor sees cross-tenant (RLS two-GUC), the last_seen COALESCE surfaces a source with
bronze activity but NO health row, and the read-derived status classifies real rows
(healthy/stale/pending). All seeded rows (config.sources, telemetry.connector_health, bronze) are
removed afterwards (D100). Loud-error posture: a missing stack env var ERRORS, never skips.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from dis_core.timestamps import now_utc
from dis_testing.fixtures import TENANTS
from dis_ui_server.auth.verifier import (
    DEV_STUB_ALGORITHM,
    DEV_STUB_AUDIENCE,
    DEV_STUB_ISSUER,
    DEV_STUB_SECRET,
)
from dis_ui_server.main import create_app

pytestmark = pytest.mark.integration

TENANT_A = str(TENANTS[0].uuid)  # buc-ees
TENANT_B = str(TENANTS[1].uuid)  # zabka-group

# Sources this suite seeds (exact-match cleanup — underscores are LIKE wildcards, so use ANY(=)).
_SRC_BRONZE_ONLY = "chlive_bronze_only"  # config.sources + bronze, NO health row -> coalesce
_SRC_HEALTHY = "chlive_healthy"  # health row, recent last_seen
_SRC_STALE = "chlive_stale"  # health row, old last_seen
_SRC_PENDING = "chlive_pending"  # config.sources only, no health, no bronze
_SRC_TENANT_B = "chlive_tenant_b"  # tenant B, for isolation
_ALL_SRCS = [_SRC_BRONZE_ONLY, _SRC_HEALTHY, _SRC_STALE, _SRC_PENDING, _SRC_TENANT_B]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _tenant_token(tenant_id: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "u-test",
            "iss": DEV_STUB_ISSUER,
            "aud": DEV_STUB_AUDIENCE,
            "iat": now,
            "exp": now + 3600,
            "user_type": "TENANT",
            "tenant_id": tenant_id,
            "roles": ["dis:read"],
        },
        DEV_STUB_SECRET,
        algorithm=DEV_STUB_ALGORITHM,
    )


def _platform_token() -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "anjali",
            "iss": DEV_STUB_ISSUER,
            "aud": DEV_STUB_AUDIENCE,
            "iat": now,
            "exp": now + 3600,
            "user_type": "PLATFORM",
            "roles": ["dis:ops", "dis:read"],
        },
        DEV_STUB_SECRET,
        algorithm=DEV_STUB_ALGORITHM,
    )


@pytest.fixture
def live_client(stack_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("POSTGRES_URL", stack_env["POSTGRES_URL"])
    with TestClient(create_app()) as client:
        yield client


@pytest.fixture
def seeded_health(stack_env: dict[str, str]) -> Iterator[Engine]:
    """Seed identity_mirror (FK target) + this suite's connectors/health/bronze; clean up after."""
    from dis_testing.identity_sync import sync_identity_mirror

    sync_identity_mirror(stack_env["POSTGRES_ADMIN_URL"], stack_env["POSTGRES_URL"])
    engine = create_engine(stack_env["POSTGRES_ADMIN_URL"])
    now = now_utc()
    recent = now - timedelta(hours=1)
    old = now - timedelta(hours=48)
    try:
        with engine.begin() as conn:
            # config.sources — the connector registry (the read's driving table).
            for tenant, src, name in [
                (TENANT_A, _SRC_BRONZE_ONLY, "Bronze Only"),
                (TENANT_A, _SRC_HEALTHY, "Healthy"),
                (TENANT_A, _SRC_STALE, "Stale"),
                (TENANT_A, _SRC_PENDING, "Pending"),
                (TENANT_B, _SRC_TENANT_B, "Tenant B Source"),
            ]:
                conn.execute(
                    text(
                        "INSERT INTO config.sources (tenant_id, source_id, display_name, channel, "
                        "schedule, status) VALUES (:t, :s, :n, 'csv_upload', 'every 15 min', 'active')"
                    ),
                    {"t": tenant, "s": src, "n": name},
                )
            # telemetry.connector_health — worker-written telemetry (recent vs old).
            conn.execute(
                text(
                    "INSERT INTO telemetry.connector_health (tenant_id, source_id, last_seen_at, status) "
                    "VALUES (:t, :s, :ts, 'healthy')"
                ),
                {"t": TENANT_A, "s": _SRC_HEALTHY, "ts": recent},
            )
            conn.execute(
                text(
                    "INSERT INTO telemetry.connector_health (tenant_id, source_id, last_seen_at, status) "
                    "VALUES (:t, :s, :ts, 'healthy')"
                ),
                {"t": TENANT_A, "s": _SRC_STALE, "ts": old},
            )
            # bronze activity for the coalesce case (config.sources + bronze, NO health row).
            conn.execute(
                text(
                    "INSERT INTO bronze.data_ingress_events "
                    "(tenant_id, source_id, dis_channel, trace_id, gcs_uri, received_at) "
                    "VALUES (:t, :s, 'csv_upload', gen_random_uuid(), 'gs://b/k.csv', :ts)"
                ),
                {"t": TENANT_A, "s": _SRC_BRONZE_ONLY, "ts": recent},
            )
        yield engine
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM telemetry.connector_health WHERE source_id = ANY(:ids)"),
                {"ids": _ALL_SRCS},
            )
            conn.execute(
                text("DELETE FROM bronze.data_ingress_events WHERE source_id = ANY(:ids)"),
                {"ids": _ALL_SRCS},
            )
            conn.execute(
                text("DELETE FROM config.sources WHERE source_id = ANY(:ids)"),
                {"ids": _ALL_SRCS},
            )
        engine.dispose()


def _items(client: TestClient, token: str) -> dict[str, dict[str, Any]]:
    resp = client.get("/api/v1/connector-health", headers=_bearer(token))
    assert resp.status_code == 200, resp.text
    return {r["source_id"]: r for r in resp.json()["items"]}


def test_tenant_sees_own_connectors_only(live_client: TestClient, seeded_health: Engine) -> None:
    items = _items(live_client, _tenant_token(TENANT_A))
    # All of tenant A's seeded connectors are present...
    assert {_SRC_BRONZE_ONLY, _SRC_HEALTHY, _SRC_STALE, _SRC_PENDING} <= set(items)
    # ...and tenant B's connector is NOT visible (RLS isolation).
    assert _SRC_TENANT_B not in items


def test_coalesce_surfaces_bronze_last_seen(live_client: TestClient, seeded_health: Engine) -> None:
    items = _items(live_client, _tenant_token(TENANT_A))
    row = items[_SRC_BRONZE_ONLY]
    # No health row, but bronze activity → last_seen is coalesced from bronze and reads healthy.
    assert row["last_seen_at"] is not None
    assert row["status"] == "healthy"


def test_status_derivation_on_real_rows(live_client: TestClient, seeded_health: Engine) -> None:
    items = _items(live_client, _tenant_token(TENANT_A))
    assert items[_SRC_HEALTHY]["status"] == "healthy"  # recent health last_seen
    assert items[_SRC_STALE]["status"] == "stale"  # old health last_seen (>24h)
    assert items[_SRC_PENDING]["status"] == "pending"  # no producer, no activity
    assert items[_SRC_PENDING]["last_seen_at"] is None


def test_platform_sees_cross_tenant(live_client: TestClient, seeded_health: Engine) -> None:
    items = _items(live_client, _platform_token())
    # PLATFORM see-all: both tenants' connectors appear in one call.
    assert _SRC_TENANT_B in items
    assert _SRC_HEALTHY in items
