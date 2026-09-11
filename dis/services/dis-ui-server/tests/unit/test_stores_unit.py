"""Unit tests for the onboarded-stores endpoints, focused on the cross-tenant read.

DB-free. The tenant-pinned ``GET /stores-onboarded`` is proven end to end by the live
integration suite (``test_stores_live.py``); here we cover the PLATFORM cross-tenant
counterpart ``GET /stores-onboarded/for-tenant/{tenant_id}`` (Finding 2a): the auth/scope
gates (401/403 that resolve BEFORE any DB touch — the DB is unreachable in unit, so a 403
proves no session opened) and, with the repo monkeypatched, that the acted-for tenant from the
PATH is what reaches the ``repos/stores.py`` chokepoint, plus the wire mapping.
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

TENANT_A = "019e5e3c-b5d3-705f-9002-2451c4ca2626"  # buc-ees
TENANT_B = "019e5e3c-b5d6-7eed-93f9-3778a7a7a160"  # zabka-group


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _fake_store_row(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "store_id": "0190ac20-6b00-7000-8b00-0000000000c1",
        "name": "Buc-ees Katy",
        "store_code": "AMB-001",
        "status": "ACTIVE",  # DB vocab; the handler lowercases via _STATUS_WIRE
        "country": "US",
        "timezone": "America/Chicago",
        "currency": "USD",
        "tax_treatment": "EXCLUSIVE",  # DB vocab; lowercased via _TAX_TREATMENT_WIRE
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# -- auth / scope gates -------------------------------------------------------------


def test_for_tenant_requires_a_token(client: TestClient) -> None:
    assert client.get(f"/api/v1/stores-onboarded/for-tenant/{TENANT_B}").status_code == 401


def test_for_tenant_tenant_caller_is_403(client: TestClient, mint_token: Callable[..., str]) -> None:
    # A TENANT caller has no business on the cross-tenant surface: require_read_scope pins them
    # to is_platform=False, and the handler refuses 403 BEFORE any DB touch (DB is unreachable).
    resp = client.get(
        f"/api/v1/stores-onboarded/for-tenant/{TENANT_B}",
        headers=_bearer(mint_token(tenant_id=TENANT_A)),  # TENANT
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "tenant_scope"


def test_for_tenant_platform_without_ops_is_403(client: TestClient, mint_token: Callable[..., str]) -> None:
    # PLATFORM see-all requires dis:ops (require_read_scope): a PLATFORM token without it is 403.
    resp = client.get(
        f"/api/v1/stores-onboarded/for-tenant/{TENANT_A}",
        headers=_bearer(mint_token(user_type="PLATFORM", tenant_id=None, roles=("dis:read",))),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "ops_role_required"


def test_for_tenant_rejects_malformed_tenant_id(client: TestClient, mint_token: Callable[..., str]) -> None:
    # The path param is a UUID: a non-UUID is a 422 before the handler runs.
    resp = client.get(
        "/api/v1/stores-onboarded/for-tenant/not-a-uuid",
        headers=_bearer(mint_token(user_type="PLATFORM", tenant_id=None, roles=("dis:ops",))),
    )
    assert resp.status_code == 422


# -- cross-tenant read (repo monkeypatched) -----------------------------------------


def test_for_tenant_platform_ops_serves_the_path_tenants_stores(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: Any
) -> None:
    seen: dict[str, Any] = {}

    async def _fake_list(_engine: Any, tenant_id: Any) -> list[Any]:
        seen["tenant_id"] = tenant_id
        return [_fake_store_row()]

    monkeypatch.setattr("dis_ui_server.handlers.stores.list_onboarded_stores", _fake_list)
    resp = client.get(
        f"/api/v1/stores-onboarded/for-tenant/{TENANT_B}",
        headers=_bearer(mint_token(user_type="PLATFORM", tenant_id=None, roles=("dis:ops", "dis:read"))),
    )
    assert resp.status_code == 200
    # The acted-for tenant from the PATH is exactly what reaches the chokepoint predicate.
    assert str(seen["tenant_id"]) == TENANT_B
    body = resp.json()
    assert len(body) == 1
    store = body[0]
    assert store["store_code"] == "AMB-001"
    assert store["status"] == "active"  # DB vocab lowercased
    assert store["tax_treatment"] == "exclusive"
    assert store["currency"] == "USD"
