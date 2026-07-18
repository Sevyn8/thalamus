"""GET /api/v1/dashboard/metrics, the DB-free half: auth gate + handler wire-mapping.

The client's database is UNREACHABLE; the repo (which would open an rls_session) is
monkeypatched to a fixed result, so these tests pin the auth posture and the
handler's mapping of raw metric values to the wire shape (incl. the quarantine-rate
rule) WITHOUT any DB touch. The real SQL is exercised by the integration test.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from dis_ui_server.repos.dashboard import DashboardMetricsData, FlowAggRow, TenantAggRow

TENANT_A = "019e5e3c-b5d3-705f-9002-2451c4ca2626"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _data(
    *,
    received: int,
    quarantined: int,
    sources_connected: int = 4,
    by_tenant: list[TenantAggRow] | None = None,
) -> DashboardMetricsData:
    return DashboardMetricsData(
        rows_ingested_24h=received,
        quarantined_rows_24h=quarantined,
        canonical_by_table=[
            ("store_sku_current_position", 65),
            ("store_sku_sale_events", 0),
            ("store_sku_change_events", 0),
        ],
        flow=[
            FlowAggRow(
                template_id="0190ac10-5a00-7000-8a00-0000000000a1",
                rows_24h=received,
                last_received_at=datetime(2026, 6, 9, 9, 12, tzinfo=UTC),
            )
        ],
        sources_connected=sources_connected,
        by_tenant=by_tenant if by_tenant is not None else [],
    )


def _patch_fetch(monkeypatch: pytest.MonkeyPatch, data: DashboardMetricsData) -> None:
    async def _fake_fetch(engine: object, tenant_id: object) -> DashboardMetricsData:
        return data

    monkeypatch.setattr("dis_ui_server.handlers.dashboard.fetch_dashboard_metrics", _fake_fetch)


def test_requires_a_token(client: TestClient) -> None:
    assert client.get("/api/v1/dashboard/metrics").status_code == 401


def test_maps_repo_result_to_wire(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_fetch(monkeypatch, _data(received=1247, quarantined=3, sources_connected=4))
    resp = client.get("/api/v1/dashboard/metrics", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 200
    body = resp.json()

    assert body["rows_ingested_24h"] == 1247
    assert body["sources_connected"] == 4  # DISTINCT connected sources for the tenant

    q = body["quarantine_24h"]
    assert q["quarantined_rows"] == 3
    assert q["received_rows"] == 1247
    assert q["rate"] == pytest.approx(3 / 1247)

    rc = body["records_in_canonical"]
    assert rc["total"] == 65
    assert {c["table"]: c["count"] for c in rc["by_table"]} == {
        "store_sku_current_position": 65,
        "store_sku_sale_events": 0,
        "store_sku_change_events": 0,
    }

    assert body["flow"][0]["template_id"] == "0190ac10-5a00-7000-8a00-0000000000a1"
    assert body["flow"][0]["rows_24h"] == 1247
    assert body["flow"][0]["last_received_at"] == "2026-06-09T09:12:00+00:00"

    # Additive safety: when the repo yields no per-tenant rows, by_tenant is an empty list
    # (the existing aggregate fields above are untouched).
    assert body["by_tenant"] == []


def test_by_tenant_breakdown_maps_and_reconciles(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A PLATFORM-style breakdown: two tenants whose rows/quarantine sum to the aggregate.
    t1 = "0190ac10-1a01-7001-8a01-0000000000a1"
    t2 = "0190ac10-1a01-7001-8a01-0000000000b2"
    by_tenant = [
        TenantAggRow(tenant_id=t1, rows_ingested_24h=1000, quarantined_rows_24h=2, tenant_name="Buc-ees"),
        TenantAggRow(tenant_id=t2, rows_ingested_24h=247, quarantined_rows_24h=1, tenant_name="Żabka Group"),
    ]
    _patch_fetch(monkeypatch, _data(received=1247, quarantined=3, by_tenant=by_tenant))
    resp = client.get("/api/v1/dashboard/metrics", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 200
    body = resp.json()

    bt = body["by_tenant"]
    assert [e["tenant_id"] for e in bt] == [t1, t2]
    # Chunk 9: tenant_name flows to the wire (the real name, not the UUID).
    assert [e["tenant_name"] for e in bt] == ["Buc-ees", "Żabka Group"]
    assert bt[0]["rows_ingested_24h"] == 1000
    assert bt[0]["quarantine_24h"] == {
        "quarantined_rows": 2,
        "received_rows": 1000,
        "rate": pytest.approx(2 / 1000),
    }
    assert bt[1]["quarantine_24h"]["rate"] == pytest.approx(1 / 247)

    # Reconcile invariant: the per-tenant slices sum to the fleet aggregate.
    assert sum(e["rows_ingested_24h"] for e in bt) == body["rows_ingested_24h"]
    fleet_q = body["quarantine_24h"]["quarantined_rows"]
    assert sum(e["quarantine_24h"]["quarantined_rows"] for e in bt) == fleet_q


def test_by_tenant_rate_null_when_tenant_has_no_ingest(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A tenant with quarantine but zero received in the window -> null rate, never a fake ratio.
    t1 = "0190ac10-1a01-7001-8a01-0000000000c3"
    # tenant_name None here exercises the LEFT-JOIN-null case (unmirrored tenant) on the wire too.
    by_tenant = [TenantAggRow(tenant_id=t1, rows_ingested_24h=0, quarantined_rows_24h=5, tenant_name=None)]
    _patch_fetch(monkeypatch, _data(received=0, quarantined=5, by_tenant=by_tenant))
    resp = client.get("/api/v1/dashboard/metrics", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 200
    entry = resp.json()["by_tenant"][0]
    assert entry["tenant_name"] is None  # LEFT-JOIN-null: unmirrored tenant → null name
    q = entry["quarantine_24h"]
    assert q["received_rows"] == 0
    assert q["rate"] is None


def test_rate_is_null_when_no_ingest(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # No denominator -> rate null (the UI shows "No ingest (24h)"), never a fake 0.
    _patch_fetch(monkeypatch, _data(received=0, quarantined=0))
    resp = client.get("/api/v1/dashboard/metrics", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 200
    q = resp.json()["quarantine_24h"]
    assert q["received_rows"] == 0
    assert q["rate"] is None
