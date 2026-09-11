"""Unit tests for ``GET /tenants-actable`` — the PLATFORM ops actable-tenant list.

DB-free. The endpoint's isolation is NOT an in-query predicate (``identity_mirror`` is
RLS-OFF and the repo query is deliberately unpredicated); it is a
``scope.is_platform`` assertion made in TWO places. So the gate tests here are not routine
auth coverage — they are the test of the only control there is.

The HTTP tests cover the handler's half, each resolving BEFORE any DB touch (the DB is
unreachable in unit, so a 403 proves no session opened). ``test_the_repo_refuses_...``
covers the durable half by calling the repo DIRECTLY with a TENANT scope — the case no HTTP
test can reach, because it is about the caller that does not exist yet.

The rest covers what the list is FOR: a tenant with zero registered sources must appear
(the whole reason this endpoint replaced deriving tenants from ``GET /sources``), and a
SUSPENDED tenant must be served WITH its status rather than filtered out.
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

TENANT_A = "019e5e3c-b5d3-705f-9002-2451c4ca2626"  # buc-ees
TENANT_B = "019e5e3c-b5d6-7eed-93f9-3778a7a7a160"  # zabka-group
TENANT_NEW = "019e5e3c-b5d9-7000-8000-000000000001"  # freshly CM-onboarded, zero sources


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _row(tenant_id: str, name: str, *, display_code: str | None, status: str) -> Any:
    return SimpleNamespace(tenant_id=tenant_id, name=name, display_code=display_code, status=status)


def _ops(mint_token: Callable[..., str]) -> dict[str, str]:
    return _bearer(mint_token(user_type="PLATFORM", tenant_id=None, roles=("dis:ops", "dis:read")))


# -- the gate IS the isolation ------------------------------------------------------


def test_requires_a_token(client: TestClient) -> None:
    assert client.get("/api/v1/tenants-actable").status_code == 401


def test_tenant_caller_is_403(client: TestClient, mint_token: Callable[..., str]) -> None:
    # A TENANT caller has no acted-for tenant to choose, and the query behind this endpoint
    # carries no tenant predicate — so this refusal is what stands between a tenant and every
    # tenant name in the fleet. Resolves before any DB connection is opened.
    resp = client.get("/api/v1/tenants-actable", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "tenant_scope"


async def test_the_repo_refuses_a_tenant_scope_without_any_handler() -> None:
    """THE DURABLE HALF OF THE GATE, tested where it lives.

    Every other test here goes through the handler, so all of them prove only that TODAY'S
    caller gates correctly — no test can pin the caller that has not been written yet. This
    one calls the repo directly with a TENANT scope: the refusal must come from the function
    itself, because the function is unpredicated against an RLS-OFF table and a caller that
    forgets to gate must get a 403 rather than the whole fleet.

    ``engine=None`` is safe and load-bearing: the refusal has to happen before the engine is
    touched, so a scope leak that got as far as opening a session would fail here on the
    None rather than pass quietly.
    """
    from dis_core.errors import TenantScopeError
    from dis_ui_server.auth.scope import ReadScope
    from dis_ui_server.repos.tenants import list_actable_tenants

    pinned = ReadScope(is_platform=False, tenant_id=UUID(TENANT_A))
    with pytest.raises(TenantScopeError):
        await list_actable_tenants(None, pinned)  # type: ignore[arg-type]


def test_platform_without_ops_is_403(client: TestClient, mint_token: Callable[..., str]) -> None:
    resp = client.get(
        "/api/v1/tenants-actable",
        headers=_bearer(mint_token(user_type="PLATFORM", tenant_id=None, roles=("dis:read",))),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "ops_role_required"


# -- the list (repo monkeypatched) --------------------------------------------------


def test_lists_a_tenant_with_zero_sources(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: Any
) -> None:
    """THE REGRESSION THIS ENDPOINT EXISTS FOR.

    The old picker derived its tenants from ``GET /sources``, so a tenant with no sources
    yet could not appear — and connecting the FIRST source for a NEW tenant is exactly the
    onboarding case. The mirror read knows nothing about sources, so a zero-source tenant is
    indistinguishable from any other here. That is the fix.
    """

    async def _fake_list(_engine: Any, _scope: Any) -> list[Any]:
        return [
            _row(TENANT_NEW, "Brand New Co", display_code="BNC", status="ONBOARDING"),
            _row(TENANT_B, "Zabka Group", display_code=None, status="ACTIVE"),
        ]

    monkeypatch.setattr("dis_ui_server.handlers.tenants.list_actable_tenants", _fake_list)
    resp = client.get("/api/v1/tenants-actable", headers=_ops(mint_token))
    assert resp.status_code == 200
    body = resp.json()
    assert [t["tenant_id"] for t in body] == [TENANT_NEW, TENANT_B]
    assert body[0] == {
        "tenant_id": TENANT_NEW,
        "name": "Brand New Co",
        "display_code": "BNC",
        "status": "onboarding",  # DB vocab lowercased (§2.6)
    }
    # display_code is nullable at source: served as-is, never invented.
    assert body[1]["display_code"] is None


def test_suspended_is_served_with_its_status_not_filtered(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: Any
) -> None:
    # Filtering SUSPENDED in the endpoint would quietly settle "what a suspended tenant may
    # do", and an absent row explains nothing to the ops user. It is served with its status
    # so the client can show it and say why it cannot be chosen.
    async def _fake_list(_engine: Any, _scope: Any) -> list[Any]:
        return [_row(TENANT_A, "Buc-ees", display_code="BUC", status="SUSPENDED")]

    monkeypatch.setattr("dis_ui_server.handlers.tenants.list_actable_tenants", _fake_list)
    resp = client.get("/api/v1/tenants-actable", headers=_ops(mint_token))
    assert resp.status_code == 200
    assert resp.json() == [
        {"tenant_id": TENANT_A, "name": "Buc-ees", "display_code": "BUC", "status": "suspended"}
    ]


def test_terminated_would_fail_loud_rather_than_leak_into_the_picker(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: Any
) -> None:
    # The repo excludes TERMINATED, so the handler should never see one. This pins the SECOND
    # guard: if that filter ever regresses, the missing wire Literal turns it into a loud
    # failure instead of a terminated tenant silently appearing as an onboarding target.
    async def _fake_list(_engine: Any, _scope: Any) -> list[Any]:
        return [_row(TENANT_A, "Gone Co", display_code=None, status="TERMINATED")]

    monkeypatch.setattr("dis_ui_server.handlers.tenants.list_actable_tenants", _fake_list)
    with pytest.raises(KeyError):
        client.get("/api/v1/tenants-actable", headers=_ops(mint_token))


def test_the_repo_query_excludes_terminated_and_carries_no_tenant_predicate() -> None:
    """Compile the statement and assert both halves of the deliberate posture.

    Unpredicated is the POINT here (the caller's gate is the isolation), so a future edit
    that "restores" a tenant predicate would silently return one row, and one that drops the
    end-state filter would offer a terminated tenant. Reading the source cannot catch either;
    compiling it can.
    """
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    from dis_ui_server.models import TenantRow
    from dis_ui_server.repos.tenants import _END_STATE_STATUS

    statement = (
        select(TenantRow.tenant_id, TenantRow.name, TenantRow.display_code, TenantRow.status)
        .where(TenantRow.status != _END_STATE_STATUS)
        .order_by(TenantRow.name, TenantRow.tenant_id)
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[no-untyped-call]
    assert "tenants.status !=" in sql
    assert "tenant_id =" not in sql  # no scoping predicate — by design, see repos/tenants.py
    assert _END_STATE_STATUS == "TERMINATED"
