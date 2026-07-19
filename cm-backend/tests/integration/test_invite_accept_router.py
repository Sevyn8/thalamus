"""Slice 2d-accept integration tests: self-service invite-accept (D-40).

The accepting user is identified by the VERIFIED TOKEN (no path/body id): row
id = token user_id, auth0_sub = token sub. No Auth0 call in the accept path, so
no mgmt client is needed. The TestClient is built without the context-manager
form (no lifespan) with app.state pre-wired, mirroring the writes-router tests.
"""
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from admin_backend.auth.stub import StubAuthClient
from admin_backend.auth.testing import make_test_jwt
from admin_backend.config import Settings, get_settings
from admin_backend.db.session import get_tenant_session
from admin_backend.main import create_app

_ACCEPT_URL = "/api/v1/tenant-users/me/accept-invitation"


@pytest.fixture
def accept_client(engine: Any, session_factory: Any, settings: Settings) -> TestClient:
    app = create_app()
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.auth_client = StubAuthClient(settings)
    app.state.mgmt_client = None  # accept path makes no Auth0 call
    return TestClient(app)


def _auth(jwt: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {jwt}"}


def _invited_token(
    settings: Settings, *, user_id: uuid.UUID, tenant_id: uuid.UUID, sub: str
) -> str:
    return make_test_jwt(
        settings, user_id=user_id, user_type="TENANT", tenant_id=tenant_id, sub=sub
    )


async def _fetch_user_row(session_factory: Any, platform_auth: Any, user_id: uuid.UUID) -> Any:
    schema = get_settings().db_schema
    async for session in get_tenant_session(platform_auth, session_factory):
        result = await session.execute(
            text(
                f"SELECT status::text AS status, auth0_sub, invitation_accepted_at, "
                f"updated_by_user_type::text AS updated_by_user_type "
                f"FROM {schema}.tenant_users WHERE id = :id"
            ),
            {"id": user_id},
        )
        return result.mappings().one()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_accept_flips_invited_to_active(
    accept_client: TestClient,
    settings: Settings,
    make_tenant: Any,
    make_tenant_user: Any,
    session_factory: Any,
    platform_auth: Any,
) -> None:
    tenant = await make_tenant(name="Accept Alpha")
    user = await make_tenant_user(tenant_id=tenant.id, status="INVITED")
    token = _invited_token(
        settings, user_id=user.id, tenant_id=tenant.id, sub="auth0|test-accept"
    )
    resp = accept_client.post(_ACCEPT_URL, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ACTIVE"

    # The row flipped with all columns set atomically (auth0_sub is response-
    # hidden, so verify against the DB directly).
    row = await _fetch_user_row(session_factory, platform_auth, user.id)
    assert row["status"] == "ACTIVE"
    assert row["auth0_sub"] == "auth0|test-accept"
    assert row["invitation_accepted_at"] is not None
    assert row["updated_by_user_type"] == "TENANT"  # sanctioned actor per D-40


# ---------------------------------------------------------------------------
# Re-accept is rejected (not a silent no-op)
# ---------------------------------------------------------------------------


async def test_reaccept_on_active_returns_409(
    accept_client: TestClient,
    settings: Settings,
    make_tenant: Any,
    make_tenant_user: Any,
) -> None:
    tenant = await make_tenant(name="Accept Bravo")
    user = await make_tenant_user(tenant_id=tenant.id, status="INVITED")
    token = _invited_token(
        settings, user_id=user.id, tenant_id=tenant.id, sub="auth0|test-accept-2"
    )
    first = accept_client.post(_ACCEPT_URL, headers=_auth(token))
    second = accept_client.post(_ACCEPT_URL, headers=_auth(token))
    assert first.status_code == 200
    assert second.status_code == 409, second.text
    assert second.json()["code"] == "INVALID_STATE_TRANSITION"


# ---------------------------------------------------------------------------
# Auth / not-found
# ---------------------------------------------------------------------------


def test_accept_unauthenticated_returns_401(accept_client: TestClient) -> None:
    resp = accept_client.post(_ACCEPT_URL)  # no Authorization header
    assert resp.status_code == 401, resp.text


async def test_accept_token_user_id_nonexistent_returns_404(
    accept_client: TestClient, settings: Settings, make_tenant: Any
) -> None:
    tenant = await make_tenant(name="Accept Charlie")
    # Valid TENANT token, but user_id points at no row.
    token = _invited_token(
        settings, user_id=uuid.uuid4(), tenant_id=tenant.id, sub="auth0|ghost"
    )
    resp = accept_client.post(_ACCEPT_URL, headers=_auth(token))
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Self-scoping: the flow keys off the token's user_id, never another user's row
# ---------------------------------------------------------------------------


async def test_accept_only_touches_the_token_user_row(
    accept_client: TestClient,
    settings: Settings,
    make_tenant: Any,
    make_tenant_user: Any,
    session_factory: Any,
    platform_auth: Any,
) -> None:
    tenant = await make_tenant(name="Accept Delta")
    user_a = await make_tenant_user(tenant_id=tenant.id, status="INVITED")
    user_b = await make_tenant_user(tenant_id=tenant.id, status="INVITED")
    # Accept as user A (there is no path/body id to supply; the row is chosen
    # solely by A's verified token user_id).
    token_a = _invited_token(
        settings, user_id=user_a.id, tenant_id=tenant.id, sub="auth0|user-a"
    )
    resp = accept_client.post(_ACCEPT_URL, headers=_auth(token_a))
    assert resp.status_code == 200, resp.text

    row_a = await _fetch_user_row(session_factory, platform_auth, user_a.id)
    row_b = await _fetch_user_row(session_factory, platform_auth, user_b.id)
    assert row_a["status"] == "ACTIVE"
    assert row_b["status"] == "INVITED"  # untouched: cross-user accept impossible
    assert row_b["auth0_sub"] is None
