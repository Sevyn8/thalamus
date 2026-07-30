"""Unit tests for ``GET /tenant-self`` — the caller's own tenant, for the topbar chip.

DB-free. This endpoint is the MIRROR IMAGE of ``/tenants-actable`` (tested next door) in
both senses, and the tests are shaped around the two things that makes different:

- ITS GATE REFUSES THE OPPOSITE PERSONA. ``/tenants-actable`` refuses TENANT; this refuses
  PLATFORM, because a PLATFORM token is cross-tenant by construction and has no own tenant.
  Answering it with an empty or invented row would be a wrong answer dressed as a success.
- ITS ISOLATION IS AN IN-QUERY PREDICATE, not a scope assertion. The repo pins
  ``WHERE tenant_id = <token tenant>`` and the predicate IS the target, so there is no
  cross-tenant read to express — which is why there is no repo-refuses-a-bad-caller test
  here to match the one next door. The corresponding test is
  ``test_reads_only_the_token_tenant``: it proves the tenant the repo is asked for comes
  from the verified token and nothing else.

THE LOAD-BEARING CASE IS THE MISSING MIRROR ROW. ``identity_mirror`` is eventually
consistent, so a tenant onboarded in Customer Master since the last mirror-sync run has no
row. That must be a 200 with nulls so the UI falls back to the UUID it already holds — never
a 404, which would turn ordinary sync lag into a client error and break a topbar.
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

TENANT_A = "019e5e3c-b5d3-705f-9002-2451c4ca2626"  # buc-ees
TENANT_UNMIRRORED = "019e5e3c-b5d9-7000-8000-000000000001"  # CM-onboarded since the last sync


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _row(name: str, display_code: str | None) -> Any:
    return SimpleNamespace(name=name, display_code=display_code)


# -- the gate -----------------------------------------------------------------------


def test_requires_a_token(client: TestClient) -> None:
    assert client.get("/api/v1/tenant-self").status_code == 401


def test_platform_caller_is_403(client: TestClient, mint_token: Callable[..., str]) -> None:
    """A PLATFORM token has no own tenant, so there is no right answer to give it.

    The PLATFORM topbar reads "Scope: All tenants" and never calls this. Refusing rather
    than returning an empty row keeps a future caller from rendering a blank tenant chip for
    an ops user and believing the mirror was empty. Resolves before any DB connection opens
    (the DB is unreachable in unit, so a 403 proves no session was opened).
    """
    resp = client.get(
        "/api/v1/tenant-self",
        headers=_bearer(
            mint_token(user_type="PLATFORM", tenant_id=None, roles=("dis:ops", "dis:read"))
        ),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "tenant_scope"


# -- the read (repo monkeypatched) --------------------------------------------------


def test_serves_the_mirrored_name_and_code(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: Any
) -> None:
    async def _fake(_engine: Any, _tenant_id: UUID) -> Any:
        return _row("Buc-ee's", "buc-001")

    monkeypatch.setattr("dis_ui_server.handlers.tenants.get_tenant_self", _fake)
    resp = client.get("/api/v1/tenant-self", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 200
    assert resp.json() == {
        "tenant_id": TENANT_A,
        "name": "Buc-ee's",
        "display_code": "buc-001",
    }


def test_unmirrored_tenant_is_200_with_nulls_not_404(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: Any
) -> None:
    """LOAD-BEARING: mirror lag must not break the topbar.

    A tenant Customer Master knows about but the last mirror-sync run did not is normal
    operation, not a client error. If this ever regresses to 404 the UI takes an error path
    over ordinary eventual consistency, and the chip that was supposed to stop showing a bare
    UUID starts showing nothing at all.
    """

    async def _fake(_engine: Any, _tenant_id: UUID) -> Any:
        return None

    monkeypatch.setattr("dis_ui_server.handlers.tenants.get_tenant_self", _fake)
    resp = client.get(
        "/api/v1/tenant-self", headers=_bearer(mint_token(tenant_id=TENANT_UNMIRRORED))
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "tenant_id": TENANT_UNMIRRORED,
        "name": None,
        "display_code": None,
    }


def test_mirror_null_display_code_is_served_as_null(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: Any
) -> None:
    """``display_code`` is nullable at source (D55) — served as-is, never invented."""

    async def _fake(_engine: Any, _tenant_id: UUID) -> Any:
        return _row("Zabka Group", None)

    monkeypatch.setattr("dis_ui_server.handlers.tenants.get_tenant_self", _fake)
    resp = client.get("/api/v1/tenant-self", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 200
    assert resp.json()["name"] == "Zabka Group"
    assert resp.json()["display_code"] is None


def test_reads_only_the_token_tenant(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: Any
) -> None:
    """THE ISOLATION, tested where this endpoint keeps it.

    Unlike ``/tenants-actable``, isolation here is the repo's in-query predicate rather than
    a scope assertion — so the thing worth pinning is that the id the repo is asked for is
    the VERIFIED TOKEN's tenant. The handler also echoes that same id onto the wire instead
    of the row's, so a mirror row could never rename which tenant the caller is.
    """
    seen: list[UUID] = []

    async def _fake(_engine: Any, tenant_id: UUID) -> Any:
        seen.append(tenant_id)
        return _row("Buc-ee's", "buc-001")

    monkeypatch.setattr("dis_ui_server.handlers.tenants.get_tenant_self", _fake)
    resp = client.get("/api/v1/tenant-self", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 200
    assert seen == [UUID(TENANT_A)]
    assert resp.json()["tenant_id"] == TENANT_A
