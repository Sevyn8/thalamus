"""Integration tests: PATCH email keeps Auth0 in sync (D-42).

Fake mgmt client (with update_user_email) injected on app.state.mgmt_client; the
TestClient is built without the context-manager form so the fake survives. The
tenant is created with a root org_node so the PATCH gate's
anchor_dep=get_tenant_user_anchor resolves; super_admin_jwt (PLATFORM) passes
ADMIN.USERS.CONFIGURE.TENANT via the GLOBAL->TENANT cascade.

The load-bearing test is the Auth0-failure rollback (D-42 clean-fail): the email
UPDATE is pending in the request transaction when the Auth0 call fires, so a
raise rolls it back and both CM and Auth0 stay at the OLD email.
"""
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from admin_backend.auth.stub import StubAuthClient
from admin_backend.config import Settings, get_settings
from admin_backend.db.session import get_tenant_session
from admin_backend.errors import Auth0ManagementError
from admin_backend.main import create_app

_CONN = "Username-Password-Authentication"


class _FakeMgmt:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail = fail

    async def update_user_email(
        self, *, user_id: str, email: str, connection: str, email_verified: bool
    ) -> None:
        self.calls.append(
            {
                "user_id": user_id,
                "email": email,
                "connection": connection,
                "email_verified": email_verified,
            }
        )
        if self._fail:
            raise Auth0ManagementError("simulated email update failure")


def _make_client(
    engine: Any, session_factory: Any, *, mgmt: Any, configured: bool = True
) -> TestClient:
    s = (
        Settings(auth0_mgmt_db_connection=_CONN)  # type: ignore[call-arg]
        if configured
        else Settings()  # type: ignore[call-arg]
    )
    app = create_app()
    app.state.settings = s
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.auth_client = StubAuthClient(s)
    app.state.mgmt_client = mgmt
    return TestClient(app)


def _auth(jwt: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {jwt}"}


async def _fetch(session_factory: Any, platform_auth: Any, user_id: uuid.UUID) -> Any:
    schema = get_settings().db_schema
    async for session in get_tenant_session(platform_auth, session_factory):
        result = await session.execute(
            text(
                f"SELECT status::text AS status, email, auth0_sub "
                f"FROM {schema}.tenant_users WHERE id = :id"
            ),
            {"id": user_id},
        )
        return result.mappings().one()


def _patch(client: TestClient, user_id: uuid.UUID, jwt: str, body: dict[str, Any]) -> Any:
    return client.patch(
        f"/api/v1/tenant-users/{user_id}", json=body, headers=_auth(jwt)
    )


# ---------------------------------------------------------------------------
# ACTIVE user: email change syncs Auth0
# ---------------------------------------------------------------------------


async def test_active_email_change_syncs_auth0(
    engine: Any,
    session_factory: Any,
    super_admin_jwt: str,
    make_tenant: Any,
    make_tenant_user: Any,
    platform_auth: Any,
) -> None:
    tenant = await make_tenant(name="Reconcile Alpha", with_root=True)
    user = await make_tenant_user(
        tenant_id=tenant.id, status="ACTIVE", email="old@reconcile.example.com"
    )
    before = await _fetch(session_factory, platform_auth, user.id)
    assert before["auth0_sub"] is not None

    mgmt = _FakeMgmt()
    client = _make_client(engine, session_factory, mgmt=mgmt)
    resp = _patch(client, user.id, super_admin_jwt, {"email": "new@reconcile.example.com"})
    assert resp.status_code == 200, resp.text

    after = await _fetch(session_factory, platform_auth, user.id)
    assert after["email"] == "new@reconcile.example.com"
    assert mgmt.calls == [
        {
            "user_id": before["auth0_sub"],
            "email": "new@reconcile.example.com",
            "connection": _CONN,
            "email_verified": True,
        }
    ]


# ---------------------------------------------------------------------------
# LOAD-BEARING: Auth0 failure rolls back the DB email change
# ---------------------------------------------------------------------------


async def test_active_email_change_auth0_failure_rolls_back(
    engine: Any,
    session_factory: Any,
    super_admin_jwt: str,
    make_tenant: Any,
    make_tenant_user: Any,
    platform_auth: Any,
) -> None:
    tenant = await make_tenant(name="Reconcile Bravo", with_root=True)
    user = await make_tenant_user(
        tenant_id=tenant.id, status="ACTIVE", email="old@reconcile.example.com"
    )
    mgmt = _FakeMgmt(fail=True)
    client = _make_client(engine, session_factory, mgmt=mgmt)

    resp = _patch(client, user.id, super_admin_jwt, {"email": "new@reconcile.example.com"})
    assert resp.status_code == 500, resp.text  # Auth0ManagementError -> INTERNAL_ERROR

    # Clean fail (D-42): the pending email UPDATE was rolled back; CM still old.
    after = await _fetch(session_factory, platform_auth, user.id)
    assert after["email"] == "old@reconcile.example.com"
    assert len(mgmt.calls) == 1  # Auth0 was attempted (and raised)


# ---------------------------------------------------------------------------
# INVITED user: pure DB write, no Auth0 call
# ---------------------------------------------------------------------------


async def test_invited_email_change_is_pure_db(
    engine: Any,
    session_factory: Any,
    super_admin_jwt: str,
    make_tenant: Any,
    make_tenant_user: Any,
    platform_auth: Any,
) -> None:
    tenant = await make_tenant(name="Reconcile Charlie", with_root=True)
    user = await make_tenant_user(
        tenant_id=tenant.id, status="INVITED", email="old@reconcile.example.com"
    )
    mgmt = _FakeMgmt()
    client = _make_client(engine, session_factory, mgmt=mgmt)

    resp = _patch(client, user.id, super_admin_jwt, {"email": "new@reconcile.example.com"})
    assert resp.status_code == 200, resp.text

    after = await _fetch(session_factory, platform_auth, user.id)
    assert after["email"] == "new@reconcile.example.com"
    assert after["auth0_sub"] is None
    assert mgmt.calls == []  # no Auth0 user to sync


# ---------------------------------------------------------------------------
# No Auth0 call on non-email edit or a no-op email
# ---------------------------------------------------------------------------


async def test_fullname_only_edit_does_not_sync_auth0(
    engine: Any,
    session_factory: Any,
    super_admin_jwt: str,
    make_tenant: Any,
    make_tenant_user: Any,
) -> None:
    tenant = await make_tenant(name="Reconcile Delta", with_root=True)
    user = await make_tenant_user(
        tenant_id=tenant.id, status="ACTIVE", email="old@reconcile.example.com"
    )
    mgmt = _FakeMgmt()
    client = _make_client(engine, session_factory, mgmt=mgmt)

    resp = _patch(client, user.id, super_admin_jwt, {"full_name": "Renamed Person"})
    assert resp.status_code == 200, resp.text
    assert mgmt.calls == []  # no email change -> no Auth0 sync


async def test_noop_email_does_not_sync_auth0(
    engine: Any,
    session_factory: Any,
    super_admin_jwt: str,
    make_tenant: Any,
    make_tenant_user: Any,
) -> None:
    tenant = await make_tenant(name="Reconcile Echo", with_root=True)
    user = await make_tenant_user(
        tenant_id=tenant.id, status="ACTIVE", email="same@reconcile.example.com"
    )
    mgmt = _FakeMgmt()
    client = _make_client(engine, session_factory, mgmt=mgmt)

    resp = _patch(client, user.id, super_admin_jwt, {"email": "same@reconcile.example.com"})
    assert resp.status_code == 200, resp.text
    assert mgmt.calls == []  # email unchanged -> no Auth0 sync


# ---------------------------------------------------------------------------
# Unconfigured mgmt on an Auth0-backed email change -> 503, DB unchanged
# ---------------------------------------------------------------------------


async def test_active_email_change_unconfigured_returns_503(
    engine: Any,
    session_factory: Any,
    super_admin_jwt: str,
    make_tenant: Any,
    make_tenant_user: Any,
    platform_auth: Any,
) -> None:
    tenant = await make_tenant(name="Reconcile Foxtrot", with_root=True)
    user = await make_tenant_user(
        tenant_id=tenant.id, status="ACTIVE", email="old@reconcile.example.com"
    )
    # mgmt_client None -> not configured for an Auth0-backed email change.
    client = _make_client(engine, session_factory, mgmt=None)

    resp = _patch(client, user.id, super_admin_jwt, {"email": "new@reconcile.example.com"})
    assert resp.status_code == 503, resp.text
    assert resp.json()["code"] == "PROVISIONING_UNAVAILABLE"

    # Do not commit a CM-only email change: rolled back.
    after = await _fetch(session_factory, platform_auth, user.id)
    assert after["email"] == "old@reconcile.example.com"
