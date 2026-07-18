"""``GET/POST /sources`` against the LIVE stack — the FIRST writable table (Phase A, D112).

Proves the WRITE path especially: a TENANT creates a source pinned to its own tenant (the
two-GUC WITH CHECK backstop), a TENANT naming another tenant is 403 (resolve_acted_for), a
PLATFORM+ops actor creates for the acted-for tenant, a TENANT cannot READ another tenant's
sources (isolation), a duplicate (tenant_id, source_id) is 409, and the 0013 backfill query
populates config.sources from existing mappings. All created rows are removed afterwards (D100).

Loud-error posture (the Slice 4/7/8 lesson): a missing stack env var ERRORS, never skips.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from dis_ui_server.main import create_app

pytestmark = pytest.mark.integration

TENANT_A = "019e5e3c-b5d3-705f-9002-2451c4ca2626"  # buc-ees (live seed)
TENANT_B = "019e5e3c-b5d6-7eed-93f9-3778a7a7a160"  # zabka-group (live seed)

# All source_ids this suite creates (exact-match cleanup — underscores would be LIKE wildcards).
_SMOKE_SOURCE_IDS = ["livesmoke_a", "livesmoke_plat", "livesmoke_dup", "backfill_smoke_src"]

# Load the migration's backfill SQL by path (module name starts with a digit -> not importable).
_MIG = Path(__file__).resolve().parents[4] / "alembic" / "versions" / "0013_config_sources_registry.py"
_spec = importlib.util.spec_from_file_location("_mig0013", _MIG)
assert _spec is not None and _spec.loader is not None
_mig0013 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mig0013)
_BACKFILL: str = _mig0013._BACKFILL


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def live_client(stack_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("POSTGRES_URL", stack_env["POSTGRES_URL"])
    with TestClient(create_app()) as client:
        yield client


@pytest.fixture
def admin_engine(stack_env: dict[str, str]) -> Iterator[Engine]:
    """A sync admin engine (bypasses RLS) for seeding/cleanup; removes all smoke rows on teardown."""
    engine = create_engine(stack_env["POSTGRES_ADMIN_URL"])
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            # config.sources has no legitimate baseline in the test env (nothing seeds it; the
            # migration backfill ran over empty mappings). The backfill TEST runs the full
            # _BACKFILL, which also picks up the seeded_identity default mapping's source_id — so
            # revert ALL of this table (D100: revert our own writes), not just the smoke ids.
            conn.execute(text("DELETE FROM config.sources"))
            # source_mappings / bronze DO carry seeded baseline — only delete our smoke ids there.
            conn.execute(
                text("DELETE FROM config.source_mappings WHERE source_id = ANY(:ids)"),
                {"ids": _SMOKE_SOURCE_IDS},
            )
            conn.execute(
                text("DELETE FROM bronze.data_ingress_events WHERE source_id = ANY(:ids)"),
                {"ids": _SMOKE_SOURCE_IDS},
            )
        engine.dispose()


def _source_ids(client: TestClient, token: str) -> set[str]:
    resp = client.get("/api/v1/sources", headers=_bearer(token))
    assert resp.status_code == 200
    return {r["source_id"] for r in resp.json()["items"]}


def test_requires_a_token(live_client: TestClient) -> None:
    assert live_client.get("/api/v1/sources").status_code == 401
    assert (
        live_client.post("/api/v1/sources", json={"source_id": "x", "display_name": "X"}).status_code == 401
    )


def test_tenant_create_is_pinned_and_isolated(
    live_client: TestClient,
    admin_engine: Engine,  # noqa: ARG001 — teardown cleanup
    seeded_identity: Engine,  # noqa: ARG001 — provides the tenant FK targets
    mint_token: Callable[..., str],
) -> None:
    a_token = mint_token(tenant_id=TENANT_A)
    b_token = mint_token(tenant_id=TENANT_B)
    # TENANT_A registers a source (WITH CHECK pins it to A).
    resp = live_client.post(
        "/api/v1/sources",
        headers=_bearer(a_token),
        json={"source_id": "livesmoke_a", "display_name": "Live Smoke A", "channel": "api"},
    )
    assert resp.status_code == 201
    assert resp.json()["channel"] == "api"
    # TENANT_A sees it; TENANT_B does NOT (tenant isolation).
    assert "livesmoke_a" in _source_ids(live_client, a_token)
    assert "livesmoke_a" not in _source_ids(live_client, b_token)


def test_tenant_naming_acted_for_is_403(
    live_client: TestClient,
    admin_engine: Engine,
    mint_token: Callable[..., str],  # noqa: ARG001
) -> None:
    resp = live_client.post(
        "/api/v1/sources",
        headers=_bearer(mint_token(tenant_id=TENANT_A)),
        json={"source_id": "livesmoke_a", "display_name": "X", "acting_for_tenant_id": TENANT_B},
    )
    assert resp.status_code == 403


def test_platform_ops_creates_for_acted_for_tenant(
    live_client: TestClient,
    admin_engine: Engine,  # noqa: ARG001
    seeded_identity: Engine,  # noqa: ARG001
    mint_token: Callable[..., str],
) -> None:
    plat = mint_token(user_type="PLATFORM", tenant_id=None, roles=("dis:ops", "dis:read"))
    resp = live_client.post(
        "/api/v1/sources",
        headers=_bearer(plat),
        json={"source_id": "livesmoke_plat", "display_name": "Plat", "acting_for_tenant_id": TENANT_A},
    )
    assert resp.status_code == 201
    # It landed in TENANT_A (the acted-for tenant), visible to A, not to B.
    assert "livesmoke_plat" in _source_ids(live_client, mint_token(tenant_id=TENANT_A))
    assert "livesmoke_plat" not in _source_ids(live_client, mint_token(tenant_id=TENANT_B))


def test_duplicate_source_is_409(
    live_client: TestClient,
    admin_engine: Engine,  # noqa: ARG001
    seeded_identity: Engine,  # noqa: ARG001
    mint_token: Callable[..., str],
) -> None:
    token = mint_token(tenant_id=TENANT_A)
    body = {"source_id": "livesmoke_dup", "display_name": "Dup"}
    assert live_client.post("/api/v1/sources", headers=_bearer(token), json=body).status_code == 201
    dup = live_client.post("/api/v1/sources", headers=_bearer(token), json=body)
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "source_already_exists"


def test_backfill_populates_from_mappings(admin_engine: Engine, seeded_identity: Engine) -> None:  # noqa: ARG001
    """The 0013 backfill query: one config.sources row per distinct mapping source_id, channel
    best-effort from the most-recent bronze dis_channel, display_name humanized."""
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO config.source_mappings (tenant_id, source_id, template_id, template_name, "
                "version_seq_per_source, status, mapping_rules, template_type) "
                "VALUES (:t, 'backfill_smoke_src', uuidv7(), 'smoke', 1, 'DRAFT', '{}'::jsonb, 'sales')"
            ),
            {"t": TENANT_A},
        )
        conn.execute(
            text(
                "INSERT INTO bronze.data_ingress_events (tenant_id, source_id, dis_channel, trace_id, "
                "gcs_uri, received_at, processing_status) "
                "VALUES (:t, 'backfill_smoke_src', 'api', uuidv7(), 'gs://x', now(), 'PROCESSED')"
            ),
            {"t": TENANT_A},
        )
        conn.execute(text(_BACKFILL))  # the migration's exact backfill SQL
        row = conn.execute(
            text(
                "SELECT display_name, channel, status FROM config.sources "
                "WHERE tenant_id = :t AND source_id = 'backfill_smoke_src'"
            ),
            {"t": TENANT_A},
        ).one()
    assert row.display_name == "Backfill Smoke Src"  # initcap(replace('_',' '))
    assert row.channel == "api"  # best-effort from the bronze dis_channel
    assert row.status == "active"
