"""``GET /api/v1/dashboard/metrics`` against the LIVE stack (read-only Dashboard reads).

Proves the new aggregate SQL is VALID against the real schemas (audit.events,
quarantine.quarantined_rows/_chunks, canonical.*) and runs tenant-scoped through
``rls_session`` for two distinct tenants. Counts depend on seed state, so this
asserts the SHAPE, the types, non-negativity, the canonical table set, and the
quarantine-rate rule (null-or-float) rather than fragile exact numbers; the
exact-count behaviour is pinned by the DB-free unit test (mapping) and is best
spot-checked against the staging tenant that carries real canonical rows.

Loud-error posture (the Slice 4/7/8 lesson): a missing stack env var ERRORS, never skips.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from dis_rls import create_rls_engine
from dis_ui_server.auth.scope import ReadScope
from dis_ui_server.main import create_app
from dis_ui_server.repos.dashboard import fetch_dashboard_metrics

pytestmark = pytest.mark.integration

TENANT_A = "019e5e3c-b5d3-705f-9002-2451c4ca2626"  # buc-ees (live seed)
TENANT_B = "019e5e3c-b5d6-7eed-93f9-3778a7a7a160"  # zabka-group (live seed)

_CANONICAL_TABLES = {
    "store_sku_current_position",
    "store_sku_sale_events",
    "store_sku_change_events",
}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def live_client(stack_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("POSTGRES_URL", stack_env["POSTGRES_URL"])
    with TestClient(create_app()) as client:
        yield client


def _assert_well_shaped(body: dict[str, object]) -> None:
    assert isinstance(body["rows_ingested_24h"], int)
    assert body["rows_ingested_24h"] >= 0

    # Sources connected: DISTINCT sources with a mapping for this tenant (tenant-scoped count).
    assert isinstance(body["sources_connected"], int) and body["sources_connected"] >= 0

    q = body["quarantine_24h"]
    assert isinstance(q, dict)
    assert isinstance(q["quarantined_rows"], int) and q["quarantined_rows"] >= 0
    assert isinstance(q["received_rows"], int) and q["received_rows"] >= 0
    # rate is null when nothing was received, else a float in [0, ...]; never fabricated.
    if q["received_rows"] == 0:
        assert q["rate"] is None
    else:
        assert isinstance(q["rate"], (int, float))

    rc = body["records_in_canonical"]
    assert isinstance(rc, dict)
    assert isinstance(rc["total"], int) and rc["total"] >= 0
    by_table = {c["table"]: c["count"] for c in rc["by_table"]}
    assert set(by_table) == _CANONICAL_TABLES
    assert all(isinstance(v, int) and v >= 0 for v in by_table.values())
    assert rc["total"] == sum(by_table.values())

    assert isinstance(body["flow"], list)
    for row in body["flow"]:
        assert isinstance(row["rows_24h"], int) and row["rows_24h"] >= 0
        assert row["last_received_at"] is None or isinstance(row["last_received_at"], str)

    # by_tenant is always present (empty for a TENANT scope); each entry is well-shaped.
    assert isinstance(body["by_tenant"], list)
    for entry in body["by_tenant"]:
        assert isinstance(entry["tenant_id"], str) and len(entry["tenant_id"]) == 36
        assert isinstance(entry["rows_ingested_24h"], int) and entry["rows_ingested_24h"] >= 0
        eq = entry["quarantine_24h"]
        assert isinstance(eq["quarantined_rows"], int) and eq["quarantined_rows"] >= 0
        assert eq["received_rows"] == entry["rows_ingested_24h"]
        if eq["received_rows"] == 0:
            assert eq["rate"] is None
        else:
            assert isinstance(eq["rate"], (int, float))


# Seed distinct DRAFT source_mappings (status=DRAFT keeps activated_at NULL — CHECK-safe).
_INSERT_SRC = text(
    "INSERT INTO config.source_mappings "
    "(tenant_id, source_id, template_id, template_name, version_seq_per_source, status, "
    "mapping_rules, template_type) "
    "VALUES (:tenant, :src, uuidv7(), 'smoke', 1, 'DRAFT', '{}'::jsonb, 'sales')"
)
_SMOKE_SRCS = ("smoke-src-a1", "smoke-src-a2", "smoke-src-b1")


async def test_sources_connected_is_tenant_scoped(stack_env: dict[str, str]) -> None:
    """The sources_connected count is tenant-scoped: seeding A's sources never moves B's count.

    Measured as deltas around a seed of 2 distinct sources for A + 1 for B (config.source_mappings
    is RLS two-GUC; the admin seed bypasses RLS, the scoped reads go through read_session). The
    autouse identity-sync fixture provides the tenant FK targets. Seeded rows are removed (D100).
    """
    admin_engine = create_async_engine(stack_env["POSTGRES_ADMIN_URL"])
    rls_engine = create_rls_engine(stack_env["POSTGRES_URL"])

    async def _count(tenant: str | None, *, platform: bool) -> int:
        scope = ReadScope(is_platform=platform, tenant_id=None if platform else UUID(tenant or ""))
        data = await fetch_dashboard_metrics(rls_engine, scope)
        return data.sources_connected

    try:
        base_a = await _count(TENANT_A, platform=False)
        base_b = await _count(TENANT_B, platform=False)
        base_p = await _count(None, platform=True)

        async with admin_engine.begin() as conn:
            await conn.execute(_INSERT_SRC, {"tenant": TENANT_A, "src": "smoke-src-a1"})
            await conn.execute(_INSERT_SRC, {"tenant": TENANT_A, "src": "smoke-src-a2"})
            await conn.execute(_INSERT_SRC, {"tenant": TENANT_B, "src": "smoke-src-b1"})

        # A sees its own 2 new sources; B is UNAFFECTED by A's seed (only its own +1); PLATFORM +3.
        assert await _count(TENANT_A, platform=False) == base_a + 2
        assert await _count(TENANT_B, platform=False) == base_b + 1
        assert await _count(None, platform=True) == base_p + 3
    finally:
        async with admin_engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM config.source_mappings WHERE source_id = ANY(:srcs)"),
                {"srcs": list(_SMOKE_SRCS)},
            )
        await admin_engine.dispose()
        await rls_engine.dispose()


def test_dashboard_metrics_valid_and_scoped_for_tenant_a(
    live_client: TestClient, mint_token: Callable[..., str]
) -> None:
    resp = live_client.get("/api/v1/dashboard/metrics", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 200
    _assert_well_shaped(resp.json())


def test_dashboard_metrics_valid_for_tenant_b(
    live_client: TestClient, mint_token: Callable[..., str]
) -> None:
    # A second, distinct tenant: the same reads run under that tenant's RLS scope.
    resp = live_client.get("/api/v1/dashboard/metrics", headers=_bearer(mint_token(tenant_id=TENANT_B)))
    assert resp.status_code == 200
    _assert_well_shaped(resp.json())


def test_by_tenant_is_empty_for_a_tenant_scope(
    live_client: TestClient, mint_token: Callable[..., str]
) -> None:
    # A TENANT scope's aggregate already IS its own numbers, so the breakdown is left empty
    # (it would only duplicate the aggregate); the breakdown is a PLATFORM feature.
    resp = live_client.get("/api/v1/dashboard/metrics", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 200
    assert resp.json()["by_tenant"] == []


def test_by_tenant_reconciles_with_the_fleet_aggregate_for_platform(
    live_client: TestClient, mint_token: Callable[..., str]
) -> None:
    # PLATFORM see-all: the breakdown carries one entry per active tenant and the per-tenant
    # slices sum to the fleet aggregate (same source rows, just GROUP BY tenant_id).
    token = mint_token(user_type="PLATFORM", tenant_id=None, roles=("dis:ops", "dis:read"))
    resp = live_client.get("/api/v1/dashboard/metrics", headers=_bearer(token))
    assert resp.status_code == 200
    body = resp.json()
    _assert_well_shaped(body)

    bt = body["by_tenant"]
    # Keyed by tenant_id only, no duplicates.
    ids = [e["tenant_id"] for e in bt]
    assert len(ids) == len(set(ids))

    # Reconcile invariant: sum of per-tenant slices == the fleet aggregate.
    assert sum(e["rows_ingested_24h"] for e in bt) == body["rows_ingested_24h"]
    assert (
        sum(e["quarantine_24h"]["quarantined_rows"] for e in bt)
        == body["quarantine_24h"]["quarantined_rows"]
    )


def test_dashboard_metrics_requires_a_token(live_client: TestClient) -> None:
    assert live_client.get("/api/v1/dashboard/metrics").status_code == 401
