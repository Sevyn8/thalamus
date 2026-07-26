"""Implicit invite-acceptance via reconciliation on first login.

Replaces the retired explicit POST /me/accept-invitation endpoint. A TENANT
user's first authenticated GET /api/v1/me/permissions (AuthBoundary's boot
call) reconciles an INVITED row: stamps auth0_sub from the verified token and
flips to ACTIVE (delegating to TenantUsersRepo.accept_invitation, same
transition + ACCEPT_INVITATION audit). Idempotent after the first login.

Repo-level tests also preserve the accept_invitation branch coverage the
retired endpoint tests carried (NOT_FOUND, INVALID_STATE, self-scoping).
"""
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from admin_backend.auth.context import AuthContext
from admin_backend.auth.stub import StubAuthClient
from admin_backend.auth.testing import make_test_jwt
from admin_backend.config import Settings, get_settings
from admin_backend.db.session import get_tenant_session
from admin_backend.main import create_app
from admin_backend.repositories.tenant_users import TenantUsersRepo

_ME_PERMISSIONS_URL = "/api/v1/me/permissions"


@pytest.fixture
def client(engine: Any, session_factory: Any, settings: Settings) -> TestClient:
    app = create_app()
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.auth_client = StubAuthClient(settings)
    app.state.mgmt_client = None  # reconciliation makes no Auth0 call
    return TestClient(app)


def _auth(jwt: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {jwt}"}


def _tenant_token(
    settings: Settings, *, user_id: uuid.UUID, tenant_id: uuid.UUID, sub: str
) -> str:
    return make_test_jwt(
        settings, user_id=user_id, user_type="TENANT", tenant_id=tenant_id, sub=sub
    )


def _tenant_auth(user_id: uuid.UUID, tenant_id: uuid.UUID, sub: str) -> AuthContext:
    return AuthContext(  # type: ignore[call-arg]
        sub=sub,
        iss="https://stub-issuer.local/",
        aud="https://api.test/",
        exp=9999999999,
        email="invitee@tenant.test",
        user_id=user_id,
        tenant_id=tenant_id,
        user_type="TENANT",
    )


async def _fetch_user_row(
    session_factory: Any, platform_auth: Any, user_id: uuid.UUID
) -> Any:
    schema = get_settings().db_schema
    async for session in get_tenant_session(platform_auth, session_factory):
        result = await session.execute(
            text(
                f"SELECT status::text AS status, auth0_sub, "
                f"invitation_accepted_at, "
                f"updated_by_user_type::text AS updated_by_user_type "
                f"FROM {schema}.tenant_users WHERE id = :id"
            ),
            {"id": user_id},
        )
        return result.mappings().one()


# ---------------------------------------------------------------------------
# Repo: reconcile_acceptance_on_login
# ---------------------------------------------------------------------------


async def test_reconcile_flips_invited_to_active(
    make_tenant: Any,
    make_tenant_user: Any,
    session_factory: Any,
    platform_auth: Any,
) -> None:
    """LOAD-BEARING: an INVITED row with auth0_sub NULL is reconciled to
    ACTIVE with auth0_sub (from the token) + invitation_accepted_at, TENANT
    actor per D-40."""
    tenant = await make_tenant(name="Reconcile Alpha")
    user = await make_tenant_user(tenant_id=tenant.id, status="INVITED")
    auth = _tenant_auth(user.id, tenant.id, sub="auth0|recon-a")
    request_id = uuid.uuid4()

    async for session in get_tenant_session(auth, session_factory):
        row = await TenantUsersRepo().reconcile_acceptance_on_login(
            session, auth=auth, request_id=request_id
        )
    assert row is not None

    persisted = await _fetch_user_row(session_factory, platform_auth, user.id)
    assert persisted["status"] == "ACTIVE"
    assert persisted["auth0_sub"] == "auth0|recon-a"
    assert persisted["invitation_accepted_at"] is not None
    assert persisted["updated_by_user_type"] == "TENANT"

    # With request_id supplied, the reconciliation emits the same
    # ACCEPT_INVITATION audit row as the (retired) explicit endpoint.
    schema = get_settings().db_schema
    async for session in get_tenant_session(platform_auth, session_factory):
        audit = await session.execute(
            text(
                f"SELECT action FROM {schema}.tenant_activity_audit_logs "
                "WHERE resource_id = :id AND action = 'ACCEPT_INVITATION'"
            ),
            {"id": user.id},
        )
    assert audit.first() is not None


async def test_reconcile_is_idempotent(
    make_tenant: Any,
    make_tenant_user: Any,
    session_factory: Any,
    platform_auth: Any,
) -> None:
    """Second reconciliation is a no-op (returns None); the row stays ACTIVE
    with the original auth0_sub. Simulates the second authenticated request."""
    tenant = await make_tenant(name="Reconcile Bravo")
    user = await make_tenant_user(tenant_id=tenant.id, status="INVITED")
    auth = _tenant_auth(user.id, tenant.id, sub="auth0|recon-b")

    async for session in get_tenant_session(auth, session_factory):
        first = await TenantUsersRepo().reconcile_acceptance_on_login(
            session, auth=auth
        )
    assert first is not None

    async for session in get_tenant_session(auth, session_factory):
        second = await TenantUsersRepo().reconcile_acceptance_on_login(
            session, auth=auth
        )
    assert second is None

    persisted = await _fetch_user_row(session_factory, platform_auth, user.id)
    assert persisted["status"] == "ACTIVE"
    assert persisted["auth0_sub"] == "auth0|recon-b"


async def test_reconcile_noop_on_already_active(
    make_tenant: Any,
    make_tenant_user: Any,
    session_factory: Any,
    platform_auth: Any,
) -> None:
    """An already-ACTIVE user (auth0_sub set) is not touched -> None."""
    tenant = await make_tenant(name="Reconcile Charlie")
    user = await make_tenant_user(tenant_id=tenant.id, status="ACTIVE")
    before = await _fetch_user_row(session_factory, platform_auth, user.id)
    auth = _tenant_auth(user.id, tenant.id, sub="auth0|should-not-apply")

    async for session in get_tenant_session(auth, session_factory):
        row = await TenantUsersRepo().reconcile_acceptance_on_login(
            session, auth=auth
        )
    assert row is None

    after = await _fetch_user_row(session_factory, platform_auth, user.id)
    assert after["auth0_sub"] == before["auth0_sub"]  # unchanged, not overwritten
    assert after["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Repo: accept_invitation branch coverage (preserved from the retired endpoint)
# ---------------------------------------------------------------------------


async def test_accept_invitation_nonexistent_row_returns_not_found(
    make_tenant: Any,
    session_factory: Any,
) -> None:
    tenant = await make_tenant(name="Accept Ghost")
    ghost_id = uuid.uuid4()
    auth = _tenant_auth(ghost_id, tenant.id, sub="auth0|ghost")
    async for session in get_tenant_session(auth, session_factory):
        row, result = await TenantUsersRepo().accept_invitation(
            session, ghost_id, auth0_sub="auth0|ghost", actor_user_id=ghost_id
        )
    assert row is None
    assert result.name == "NOT_FOUND"


async def test_accept_invitation_on_active_returns_invalid_state(
    make_tenant: Any,
    make_tenant_user: Any,
    session_factory: Any,
) -> None:
    tenant = await make_tenant(name="Accept Active")
    user = await make_tenant_user(tenant_id=tenant.id, status="ACTIVE")
    auth = _tenant_auth(user.id, tenant.id, sub="auth0|reaccept")
    async for session in get_tenant_session(auth, session_factory):
        row, result = await TenantUsersRepo().accept_invitation(
            session, user.id, auth0_sub="auth0|reaccept", actor_user_id=user.id
        )
    assert row is None
    assert result.name == "INVALID_STATE"


# ---------------------------------------------------------------------------
# Router: GET /me/permissions is the reconciliation hook
# ---------------------------------------------------------------------------


async def test_me_permissions_reconciles_invited_tenant_user(
    client: TestClient,
    settings: Settings,
    make_tenant: Any,
    make_tenant_user: Any,
    session_factory: Any,
    platform_auth: Any,
) -> None:
    """LOAD-BEARING: an INVITED TENANT user's first GET /me/permissions
    stamps auth0_sub + flips ACTIVE (implicit acceptance on first login)."""
    tenant = await make_tenant(name="MePerm Alpha")
    user = await make_tenant_user(tenant_id=tenant.id, status="INVITED")
    token = _tenant_token(
        settings, user_id=user.id, tenant_id=tenant.id, sub="auth0|meperm-a"
    )

    resp = client.get(_ME_PERMISSIONS_URL, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json()["permissions"], list)

    persisted = await _fetch_user_row(session_factory, platform_auth, user.id)
    assert persisted["status"] == "ACTIVE"
    assert persisted["auth0_sub"] == "auth0|meperm-a"
    assert persisted["invitation_accepted_at"] is not None


async def test_me_permissions_reconcile_is_idempotent(
    client: TestClient,
    settings: Settings,
    make_tenant: Any,
    make_tenant_user: Any,
    session_factory: Any,
    platform_auth: Any,
) -> None:
    """A second GET does not error and leaves the ACTIVE row unchanged."""
    tenant = await make_tenant(name="MePerm Bravo")
    user = await make_tenant_user(tenant_id=tenant.id, status="INVITED")
    token = _tenant_token(
        settings, user_id=user.id, tenant_id=tenant.id, sub="auth0|meperm-b"
    )
    assert client.get(_ME_PERMISSIONS_URL, headers=_auth(token)).status_code == 200
    assert client.get(_ME_PERMISSIONS_URL, headers=_auth(token)).status_code == 200

    persisted = await _fetch_user_row(session_factory, platform_auth, user.id)
    assert persisted["status"] == "ACTIVE"
    assert persisted["auth0_sub"] == "auth0|meperm-b"


async def test_me_permissions_platform_caller_no_reconcile(
    client: TestClient,
    settings: Settings,
    make_platform_user: Any,
) -> None:
    """PLATFORM callers skip reconciliation entirely (no tenant_users row);
    the endpoint still returns their grants without error."""
    pu = await make_platform_user(
        email=f"plat-{uuid.uuid4().hex[:8]}@ithina.test"
    )
    token = make_test_jwt(
        settings, user_id=pu.id, user_type="PLATFORM", sub="auth0|plat"
    )
    resp = client.get(_ME_PERMISSIONS_URL, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json()["permissions"], list)
