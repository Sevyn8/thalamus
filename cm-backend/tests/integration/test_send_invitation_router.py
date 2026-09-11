"""Integration tests: PLATFORM staff send-invitation action.

Fake mgmt client + fake email sender injected on app.state (no live Auth0 /
SendGrid). The TestClient is built without the context-manager form so the
injected fakes survive (lifespan would overwrite app.state). Order matters:
ticket + email happen before the invited_at write, so a send failure leaves
invited_at NULL (retriable) - asserted below.
"""
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from admin_backend.auth.auth0_management import Auth0User
from admin_backend.auth.stub import StubAuthClient
from admin_backend.auth.testing import make_test_jwt
from admin_backend.config import Settings, get_settings
from admin_backend.db.session import get_tenant_session
from admin_backend.errors import EmailSendError
from admin_backend.main import create_app


class _FakeMgmt:
    def __init__(self, *, found: bool = True) -> None:
        self._found = found
        self.ticket_calls: list[dict[str, Any]] = []

    async def get_user_by_email(self, email: str) -> Auth0User | None:
        return Auth0User(user_id="auth0|xyz", email=email) if self._found else None

    async def create_password_change_ticket(self, *, user_id: str, result_url: str) -> str:
        self.ticket_calls.append({"user_id": user_id, "result_url": result_url})
        return "https://sevyn8.us.auth0.com/lo/reset?ticket=abc"


class _FakeEmail:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[dict[str, str]] = []
        self._fail = fail

    async def send_email(self, *, to: str, subject: str, body: str) -> None:
        if self._fail:
            raise EmailSendError("simulated send failure")
        self.sent.append({"to": to, "subject": subject, "body": body})


def _make_client(
    engine: Any, session_factory: Any, *, mgmt: Any, email_sender: Any, configured: bool = True
) -> TestClient:
    s = (
        Settings(  # type: ignore[call-arg]
            sendgrid_api_key="SG.test",
            auth0_ticket_result_url="https://app.sevyn8.com/welcome",
        )
        if configured
        else Settings()  # type: ignore[call-arg]  # no sendgrid key / result_url
    )
    app = create_app()
    app.state.settings = s
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.auth_client = StubAuthClient(s)
    app.state.mgmt_client = mgmt
    app.state.email_sender = email_sender
    return TestClient(app)


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
                f"updated_by_user_type::text AS updated_by_user_type "
                f"FROM {schema}.tenant_users WHERE id = :id"
            ),
            {"id": user_id},
        )
        return result.mappings().one()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_send_invitation_happy(
    engine: Any,
    session_factory: Any,
    super_admin_jwt: str,
    make_tenant: Any,
    make_tenant_user: Any,
    platform_auth: Any,
) -> None:
    tenant = await make_tenant(name="Send Alpha")
    user = await make_tenant_user(tenant_id=tenant.id, status="INVITED", email="a@send.test")
    mgmt = _FakeMgmt(found=True)
    email = _FakeEmail()
    client = _make_client(engine, session_factory, mgmt=mgmt, email_sender=email)

    resp = client.post(
        f"/api/v1/tenant-users/{user.id}/send-invitation", headers=_auth(super_admin_jwt)
    )
    assert resp.status_code == 200, resp.text

    # ticket generated for the re-looked-up Auth0 user; email carries the URL.
    assert mgmt.ticket_calls == [
        {"user_id": "auth0|xyz", "result_url": "https://app.sevyn8.com/welcome"}
    ]
    assert len(email.sent) == 1
    assert email.sent[0]["to"] == "a@send.test"
    assert "https://sevyn8.us.auth0.com/lo/reset?ticket=abc" in email.sent[0]["body"]

    # invited_at set (PLATFORM actor); row stays INVITED, auth0_sub still NULL.
    row = await _fetch_user_row(session_factory, platform_auth, user.id)
    assert row["invited_at"] is not None
    assert row["updated_by_user_type"] == "PLATFORM"
    assert row["status"] == "INVITED"
    assert row["auth0_sub"] is None


# ---------------------------------------------------------------------------
# RBAC / not-found / not-configured / not-provisioned
# ---------------------------------------------------------------------------


async def test_send_invitation_non_platform_denied(
    engine: Any, session_factory: Any, settings: Settings, make_tenant: Any, make_tenant_user: Any
) -> None:
    tenant = await make_tenant(name="Send Bravo")
    user = await make_tenant_user(tenant_id=tenant.id, status="INVITED")
    client = _make_client(
        engine, session_factory, mgmt=_FakeMgmt(), email_sender=_FakeEmail()
    )
    resp = client.post(
        f"/api/v1/tenant-users/{user.id}/send-invitation",
        headers=_auth(_tenant_jwt(settings, tenant.id)),
    )
    assert resp.status_code == 403, resp.text


async def test_send_invitation_missing_user_404(
    engine: Any, session_factory: Any, super_admin_jwt: str
) -> None:
    client = _make_client(
        engine, session_factory, mgmt=_FakeMgmt(), email_sender=_FakeEmail()
    )
    resp = client.post(
        f"/api/v1/tenant-users/{uuid.uuid4()}/send-invitation", headers=_auth(super_admin_jwt)
    )
    assert resp.status_code == 404, resp.text


async def test_send_invitation_unconfigured_returns_503(
    engine: Any,
    session_factory: Any,
    super_admin_jwt: str,
    make_tenant: Any,
    make_tenant_user: Any,
) -> None:
    tenant = await make_tenant(name="Send Charlie")
    user = await make_tenant_user(tenant_id=tenant.id, status="INVITED")
    # email_sender None -> not configured.
    client = _make_client(engine, session_factory, mgmt=_FakeMgmt(), email_sender=None)
    resp = client.post(
        f"/api/v1/tenant-users/{user.id}/send-invitation", headers=_auth(super_admin_jwt)
    )
    assert resp.status_code == 503, resp.text
    assert resp.json()["code"] == "PROVISIONING_UNAVAILABLE"


async def test_send_invitation_user_not_in_auth0_returns_409(
    engine: Any,
    session_factory: Any,
    super_admin_jwt: str,
    make_tenant: Any,
    make_tenant_user: Any,
) -> None:
    tenant = await make_tenant(name="Send Delta")
    user = await make_tenant_user(tenant_id=tenant.id, status="INVITED")
    client = _make_client(
        engine, session_factory, mgmt=_FakeMgmt(found=False), email_sender=_FakeEmail()
    )
    resp = client.post(
        f"/api/v1/tenant-users/{user.id}/send-invitation", headers=_auth(super_admin_jwt)
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "USER_NOT_PROVISIONED"


# ---------------------------------------------------------------------------
# Email failure -> 500, invited_at stays NULL (retriable)
# ---------------------------------------------------------------------------


async def test_send_invitation_email_failure_leaves_invited_at_null(
    engine: Any,
    session_factory: Any,
    super_admin_jwt: str,
    make_tenant: Any,
    make_tenant_user: Any,
    platform_auth: Any,
) -> None:
    tenant = await make_tenant(name="Send Echo")
    user = await make_tenant_user(tenant_id=tenant.id, status="INVITED")
    client = _make_client(
        engine, session_factory, mgmt=_FakeMgmt(), email_sender=_FakeEmail(fail=True)
    )
    resp = client.post(
        f"/api/v1/tenant-users/{user.id}/send-invitation", headers=_auth(super_admin_jwt)
    )
    assert resp.status_code == 500, resp.text
    # DB-first: the send failed BEFORE the invited_at write, so it stays NULL.
    row = await _fetch_user_row(session_factory, platform_auth, user.id)
    assert row["invited_at"] is None
    assert row["status"] == "INVITED"
