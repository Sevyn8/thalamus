"""Integration tests for the Auth0 provisioning endpoints.

Auth0 is faked at the seam (a _FakeMgmt satisfying Auth0ManagementClientProtocol
injected onto app.state.mgmt_client); the live tenant is never hit. The RBAC
gate + RLS row-load + provisioning service run for real against committed rows.

The TestClient is built WITHOUT the context-manager form on purpose: running
the lifespan would overwrite app.state.mgmt_client (STUB mode -> None). The
manually-wired app.state (mirroring the conftest `client` pattern) keeps the
injected fake in place.

Key assertions: RBAC (non-PLATFORM -> 403), 404 on a missing row, idempotent
get-or-create (calling twice does not double-create), the correct app_metadata
(tenant_id / user_type / cm_user_id, NOT email; cm_user_id == tenant_users.id),
that provisioning writes NOTHING to the DB (row stays INVITED / auth0_sub NULL /
invited_at NULL), and mgmt-not-configured / connection-missing -> 503, not 500.
"""
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from admin_backend.auth.auth0_management import (
    Auth0ManagementClientProtocol,
    Auth0User,
    Organization,
)
from admin_backend.auth.stub import StubAuthClient
from admin_backend.auth.testing import make_test_jwt
from admin_backend.config import Settings, get_settings
from admin_backend.db.session import get_tenant_session
from admin_backend.main import create_app


# ---------------------------------------------------------------------------
# Fake Auth0 management client (records calls; idempotent get-or-create)
# ---------------------------------------------------------------------------


class _FakeMgmt:
    def __init__(self) -> None:
        self.orgs: dict[str, Organization] = {}
        self.users: dict[str, Auth0User] = {}
        self.member_adds: list[tuple[str, str]] = []
        self.created_users: list[dict[str, Any]] = []
        self.updated_metadata: list[dict[str, Any]] = []
        self.org_create_count = 0
        self._org_seq = 0
        self._user_seq = 0

    async def create_organization(self, *, name: str, display_name: str) -> Organization:
        self._org_seq += 1
        self.org_create_count += 1
        org = Organization(id=f"org_{self._org_seq}", name=name, display_name=display_name)
        self.orgs[name] = org
        return org

    async def get_organization_by_name(self, name: str) -> Organization | None:
        return self.orgs.get(name)

    async def create_user(
        self,
        *,
        email: str,
        connection: str,
        app_metadata: dict[str, Any] | None = None,
        email_verified: bool = False,
    ) -> Auth0User:
        self._user_seq += 1
        user = Auth0User(user_id=f"auth0|{self._user_seq}", email=email)
        self.users[email] = user
        self.created_users.append(
            {
                "email": email,
                "connection": connection,
                "app_metadata": app_metadata,
                "email_verified": email_verified,
            }
        )
        return user

    async def get_user_by_email(self, email: str) -> Auth0User | None:
        return self.users.get(email)

    async def add_organization_member(self, *, org_id: str, user_id: str) -> None:
        self.member_adds.append((org_id, user_id))

    async def update_user_app_metadata(
        self, *, user_id: str, app_metadata: dict[str, Any]
    ) -> Auth0User:
        self.updated_metadata.append({"user_id": user_id, "app_metadata": app_metadata})
        for user in self.users.values():
            if user.user_id == user_id:
                return user
        return Auth0User(user_id=user_id, email=None)


# ---------------------------------------------------------------------------
# Client builders (no lifespan; fake injected on app.state)
# ---------------------------------------------------------------------------


def _make_client(engine: Any, session_factory: Any, *, mgmt: Any, connection: str | None) -> TestClient:
    s = (
        Settings(auth0_mgmt_db_connection=connection)  # type: ignore[call-arg]
        if connection is not None
        else Settings()  # type: ignore[call-arg]
    )
    app = create_app()
    app.state.settings = s
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.auth_client = StubAuthClient(s)
    app.state.mgmt_client = mgmt
    return TestClient(app)


@pytest.fixture
def fake_mgmt() -> _FakeMgmt:
    return _FakeMgmt()


@pytest.fixture
def provision_client(engine: Any, session_factory: Any, fake_mgmt: _FakeMgmt) -> TestClient:
    return _make_client(
        engine, session_factory, mgmt=fake_mgmt, connection="Username-Password-Authentication"
    )


@pytest.fixture
def no_mgmt_client(engine: Any, session_factory: Any) -> TestClient:
    return _make_client(
        engine, session_factory, mgmt=None, connection="Username-Password-Authentication"
    )


@pytest.fixture
def no_conn_client(engine: Any, session_factory: Any, fake_mgmt: _FakeMgmt) -> TestClient:
    return _make_client(engine, session_factory, mgmt=fake_mgmt, connection=None)


def _auth(jwt: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {jwt}"}


def _tenant_jwt(settings: Settings, tenant_id: uuid.UUID) -> str:
    return make_test_jwt(
        settings, user_id=uuid.uuid4(), user_type="TENANT", tenant_id=tenant_id
    )


async def _fetch_user_row(session_factory: Any, platform_auth: Any, user_id: uuid.UUID) -> Any:
    schema = get_settings().db_schema
    async for session in get_tenant_session(platform_auth, session_factory):
        result = await session.execute(
            text(
                f"SELECT status::text AS status, auth0_sub, invited_at, "
                f"invitation_accepted_at FROM {schema}.tenant_users WHERE id = :id"
            ),
            {"id": user_id},
        )
        return result.mappings().one()


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


def test_fake_satisfies_protocol(fake_mgmt: _FakeMgmt) -> None:
    assert isinstance(fake_mgmt, Auth0ManagementClientProtocol)


# ---------------------------------------------------------------------------
# Tenant Organization provisioning
# ---------------------------------------------------------------------------


async def test_tenant_provision_creates_org(
    provision_client: TestClient, super_admin_jwt: str, fake_mgmt: _FakeMgmt, make_tenant: Any
) -> None:
    tenant = await make_tenant(name="Provision Alpha")
    resp = provision_client.post(
        f"/api/v1/tenants/{tenant.id}/provision-auth0", headers=_auth(super_admin_jwt)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["org_name"] == f"tenant-{tenant.id}"
    assert body["created"] is True
    assert fake_mgmt.org_create_count == 1

    # The org id is persisted, so onboarding-state now
    # reports a durable TRUE (was UNKNOWN before this slice).
    state = provision_client.get(
        f"/api/v1/tenants/{tenant.id}/onboarding",
        headers=_auth(super_admin_jwt),
    )
    assert state.status_code == 200, state.text
    assert state.json()["provisioning"]["auth0_organization"] == "TRUE"


async def test_tenant_provision_is_idempotent(
    provision_client: TestClient, super_admin_jwt: str, fake_mgmt: _FakeMgmt, make_tenant: Any
) -> None:
    tenant = await make_tenant(name="Provision Bravo")
    url = f"/api/v1/tenants/{tenant.id}/provision-auth0"
    first = provision_client.post(url, headers=_auth(super_admin_jwt))
    second = provision_client.post(url, headers=_auth(super_admin_jwt))
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["created"] is True
    assert second.json()["created"] is False  # get-or-create found the existing org
    assert fake_mgmt.org_create_count == 1  # not double-created


async def test_tenant_provision_non_platform_denied(
    provision_client: TestClient, settings: Settings, make_tenant: Any
) -> None:
    tenant = await make_tenant(name="Provision Charlie")
    resp = provision_client.post(
        f"/api/v1/tenants/{tenant.id}/provision-auth0",
        headers=_auth(_tenant_jwt(settings, tenant.id)),
    )
    assert resp.status_code == 403, resp.text


async def test_tenant_provision_missing_tenant_404(
    provision_client: TestClient, super_admin_jwt: str
) -> None:
    resp = provision_client.post(
        f"/api/v1/tenants/{uuid.uuid4()}/provision-auth0", headers=_auth(super_admin_jwt)
    )
    assert resp.status_code == 404, resp.text


async def test_tenant_provision_no_mgmt_returns_503(
    no_mgmt_client: TestClient, super_admin_jwt: str, make_tenant: Any
) -> None:
    tenant = await make_tenant(name="Provision Delta")
    resp = no_mgmt_client.post(
        f"/api/v1/tenants/{tenant.id}/provision-auth0", headers=_auth(super_admin_jwt)
    )
    assert resp.status_code == 503, resp.text
    assert resp.json()["code"] == "PROVISIONING_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Tenant-user provisioning
# ---------------------------------------------------------------------------


async def test_tenant_user_provision_creates_user_org_membership_metadata(
    provision_client: TestClient,
    super_admin_jwt: str,
    fake_mgmt: _FakeMgmt,
    make_tenant: Any,
    make_tenant_user: Any,
) -> None:
    tenant = await make_tenant(name="Provision Echo")
    # Explicit, schema-valid email (lowercase; matches the tenant_users email
    # CHECK). The factory inserts this into the NOT NULL email column; the
    # endpoint reads the committed row and passes this exact value to
    # create_user. (The bare ORM object the factory returns omits email, so we
    # assert against the literal we inserted, not user.email.)
    email = "alice@provision-echo.test"
    user = await make_tenant_user(tenant_id=tenant.id, status="INVITED", email=email)
    resp = provision_client.post(
        f"/api/v1/tenant-users/{user.id}/provision-auth0", headers=_auth(super_admin_jwt)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user_created"] is True
    assert body["auth0_user_id"].startswith("auth0|")

    # create_user got the right connection + app_metadata (no email key).
    assert len(fake_mgmt.created_users) == 1
    call = fake_mgmt.created_users[0]
    assert call["connection"] == "Username-Password-Authentication"
    assert call["email"] == email  # the row's real email flowed through unchanged
    assert call["app_metadata"] == {
        "tenant_id": str(tenant.id),
        "user_type": "TENANT",
        "cm_user_id": str(user.id),
    }
    assert "email" not in call["app_metadata"]
    # membership added; org created once.
    assert len(fake_mgmt.member_adds) == 1
    assert fake_mgmt.org_create_count == 1


async def test_tenant_user_provision_idempotent(
    provision_client: TestClient,
    super_admin_jwt: str,
    fake_mgmt: _FakeMgmt,
    make_tenant: Any,
    make_tenant_user: Any,
) -> None:
    tenant = await make_tenant(name="Provision Foxtrot")
    user = await make_tenant_user(tenant_id=tenant.id, status="INVITED")
    url = f"/api/v1/tenant-users/{user.id}/provision-auth0"
    first = provision_client.post(url, headers=_auth(super_admin_jwt))
    second = provision_client.post(url, headers=_auth(super_admin_jwt))
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["user_created"] is True
    assert second.json()["user_created"] is False  # existing user found by email
    assert len(fake_mgmt.created_users) == 1  # not double-created
    assert len(fake_mgmt.updated_metadata) == 1  # second call refreshed metadata


async def test_tenant_user_provision_writes_nothing_to_db(
    provision_client: TestClient,
    super_admin_jwt: str,
    make_tenant: Any,
    make_tenant_user: Any,
    session_factory: Any,
    platform_auth: Any,
) -> None:
    tenant = await make_tenant(name="Provision Golf")
    user = await make_tenant_user(tenant_id=tenant.id, status="INVITED")
    resp = provision_client.post(
        f"/api/v1/tenant-users/{user.id}/provision-auth0", headers=_auth(super_admin_jwt)
    )
    assert resp.status_code == 200, resp.text
    # Provisioning is Auth0-side only: the row is untouched.
    row = await _fetch_user_row(session_factory, platform_auth, user.id)
    assert row["status"] == "INVITED"
    assert row["auth0_sub"] is None
    assert row["invited_at"] is None
    assert row["invitation_accepted_at"] is None


async def test_tenant_user_provision_non_platform_denied(
    provision_client: TestClient,
    settings: Settings,
    make_tenant: Any,
    make_tenant_user: Any,
) -> None:
    tenant = await make_tenant(name="Provision Hotel")
    user = await make_tenant_user(tenant_id=tenant.id, status="INVITED")
    resp = provision_client.post(
        f"/api/v1/tenant-users/{user.id}/provision-auth0",
        headers=_auth(_tenant_jwt(settings, tenant.id)),
    )
    assert resp.status_code == 403, resp.text


async def test_tenant_user_provision_missing_user_404(
    provision_client: TestClient, super_admin_jwt: str
) -> None:
    resp = provision_client.post(
        f"/api/v1/tenant-users/{uuid.uuid4()}/provision-auth0",
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 404, resp.text


async def test_tenant_user_provision_no_connection_returns_503(
    no_conn_client: TestClient,
    super_admin_jwt: str,
    make_tenant: Any,
    make_tenant_user: Any,
) -> None:
    tenant = await make_tenant(name="Provision India")
    user = await make_tenant_user(tenant_id=tenant.id, status="INVITED")
    resp = no_conn_client.post(
        f"/api/v1/tenant-users/{user.id}/provision-auth0", headers=_auth(super_admin_jwt)
    )
    assert resp.status_code == 503, resp.text
    assert resp.json()["code"] == "PROVISIONING_UNAVAILABLE"
