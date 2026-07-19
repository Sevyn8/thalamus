"""Slice 2b offline unit tests for Auth0ManagementClient.

No network: an httpx.MockTransport backs the injected AsyncClient, so the REAL
request-building and response-parsing run while the live Auth0 tenant is never
hit (mirrors the Slice-1 test_auth0 discipline). Covers M2M token
acquisition / caching / refresh, each Management operation's request shape and
response parsing, and failure mapping to Auth0ManagementError.
"""
import json
from typing import Any, Callable

import httpx
import pytest

from admin_backend.auth.auth0_management import (
    Auth0ManagementClient,
    Auth0ManagementClientProtocol,
    Auth0User,
    Organization,
)
from admin_backend.config import Settings
from admin_backend.errors import Auth0ManagementError

_ISS = "https://sevyn8.us.auth0.com/"
_AUD = "https://api.sevyn8.com"
_MGMT_BASE = "https://sevyn8.us.auth0.com/api/v2/"  # derived audience


class _Recorder:
    """MockTransport handler: records requests, serves the token endpoint, and
    delegates Management paths to a per-test responder."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.token_calls = 0
        self.token_status = 200
        self.token_expires_in = 86400
        self.responder: Callable[[httpx.Request], httpx.Response] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/oauth/token":
            self.token_calls += 1
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "denied"})
            return httpx.Response(
                200,
                json={
                    "access_token": f"tok-{self.token_calls}",
                    "expires_in": self.token_expires_in,
                    "token_type": "Bearer",
                },
            )
        if self.responder is None:
            return httpx.Response(500, json={})
        return self.responder(request)


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        jwt_issuer=_ISS,
        jwt_audience=_AUD,
        auth0_mgmt_client_id="cid",
        auth0_mgmt_client_secret="csecret",
    )


def _client(settings: Settings, rec: _Recorder) -> Auth0ManagementClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(rec), base_url=_MGMT_BASE)
    return Auth0ManagementClient(settings, http_client=http)


def _body(request: httpx.Request) -> Any:
    return json.loads(request.content)


# ---------------------------------------------------------------------------
# Construction + settings
# ---------------------------------------------------------------------------


def test_mgmt_audience_derived_from_issuer(settings: Settings) -> None:
    assert settings.auth0_mgmt_audience == _MGMT_BASE


def test_construction_requires_credentials() -> None:
    no_creds = Settings(  # type: ignore[call-arg]
        jwt_issuer=_ISS, jwt_audience=_AUD
    )  # no auth0_mgmt_client_id / secret
    with pytest.raises(Auth0ManagementError):
        Auth0ManagementClient(no_creds)


def test_satisfies_protocol(settings: Settings) -> None:
    client = _client(settings, _Recorder())
    assert isinstance(client, Auth0ManagementClientProtocol)


# ---------------------------------------------------------------------------
# M2M token: acquisition, caching, refresh
# ---------------------------------------------------------------------------


async def test_token_acquired_and_authorization_header(settings: Settings) -> None:
    rec = _Recorder()
    rec.responder = lambda r: httpx.Response(
        201, json={"id": "org_1", "name": "org-x", "display_name": "X"}
    )
    client = _client(settings, rec)
    await client.create_organization(name="org-x", display_name="X")
    # The token was fetched, and the Management call carried the bearer.
    assert rec.token_calls == 1
    mgmt = [r for r in rec.requests if r.url.path == "/api/v2/organizations"][0]
    assert mgmt.headers.get("authorization") == "Bearer tok-1"


async def test_token_cached_across_calls(settings: Settings) -> None:
    rec = _Recorder()
    rec.responder = lambda r: httpx.Response(
        201, json={"id": "org_1", "name": "org-x", "display_name": "X"}
    )
    client = _client(settings, rec)
    await client.create_organization(name="org-x", display_name="X")
    await client.create_organization(name="org-y", display_name="Y")
    assert rec.token_calls == 1  # second call reused the cached token


async def test_token_refreshed_on_expiry(settings: Settings) -> None:
    rec = _Recorder()
    rec.responder = lambda r: httpx.Response(
        201, json={"id": "org_1", "name": "org-x", "display_name": "X"}
    )
    client = _client(settings, rec)
    await client.create_organization(name="org-x", display_name="X")
    # Force the cached token past expiry; the next call refetches.
    client._token_expiry_monotonic = 0.0  # type: ignore[attr-defined]
    await client.create_organization(name="org-y", display_name="Y")
    assert rec.token_calls == 2
    second = [r for r in rec.requests if r.url.path == "/api/v2/organizations"][1]
    assert second.headers.get("authorization") == "Bearer tok-2"


async def test_token_endpoint_failure_maps_to_typed_error(settings: Settings) -> None:
    rec = _Recorder()
    rec.token_status = 401
    client = _client(settings, rec)
    with pytest.raises(Auth0ManagementError):
        await client.get_user_by_email("x@y.test")


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------


async def test_create_organization_request_shape_and_parse(settings: Settings) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v2/organizations"
        assert _body(request) == {"name": "org-abc", "display_name": "Acme"}
        return httpx.Response(
            201, json={"id": "org_123", "name": "org-abc", "display_name": "Acme"}
        )

    rec = _Recorder()
    rec.responder = responder
    org = await _client(settings, rec).create_organization(
        name="org-abc", display_name="Acme"
    )
    assert isinstance(org, Organization)
    assert org.id == "org_123"
    assert org.name == "org-abc"


async def test_get_organization_by_name_found(settings: Settings) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v2/organizations/name/org-abc"
        return httpx.Response(200, json={"id": "org_123", "name": "org-abc"})

    rec = _Recorder()
    rec.responder = responder
    org = await _client(settings, rec).get_organization_by_name("org-abc")
    assert org is not None
    assert org.id == "org_123"


async def test_get_organization_by_name_missing_returns_none(settings: Settings) -> None:
    rec = _Recorder()
    rec.responder = lambda r: httpx.Response(404, json={"statusCode": 404})
    org = await _client(settings, rec).get_organization_by_name("nope")
    assert org is None


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


async def test_create_user_request_shape_and_parse(settings: Settings) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v2/users"
        assert _body(request) == {
            "email": "a@tenant.test",
            "connection": "Username-Password-Authentication",
            "email_verified": False,
            "app_metadata": {"tenant_id": "t1", "user_type": "TENANT"},
        }
        return httpx.Response(
            201, json={"user_id": "auth0|abc", "email": "a@tenant.test"}
        )

    rec = _Recorder()
    rec.responder = responder
    user = await _client(settings, rec).create_user(
        email="a@tenant.test",
        connection="Username-Password-Authentication",
        app_metadata={"tenant_id": "t1", "user_type": "TENANT"},
    )
    assert isinstance(user, Auth0User)
    assert user.user_id == "auth0|abc"


async def test_get_user_by_email_found(settings: Settings) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v2/users-by-email"
        assert request.url.params.get("email") == "a@tenant.test"
        return httpx.Response(200, json=[{"user_id": "auth0|abc", "email": "a@tenant.test"}])

    rec = _Recorder()
    rec.responder = responder
    user = await _client(settings, rec).get_user_by_email("a@tenant.test")
    assert user is not None
    assert user.user_id == "auth0|abc"


async def test_get_user_by_email_empty_returns_none(settings: Settings) -> None:
    rec = _Recorder()
    rec.responder = lambda r: httpx.Response(200, json=[])
    user = await _client(settings, rec).get_user_by_email("missing@tenant.test")
    assert user is None


async def test_update_user_app_metadata_request_and_parse(settings: Settings) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == "/api/v2/users/auth0|abc"
        assert _body(request) == {"app_metadata": {"tenant_id": "t1"}}
        return httpx.Response(200, json={"user_id": "auth0|abc", "email": "a@tenant.test"})

    rec = _Recorder()
    rec.responder = responder
    user = await _client(settings, rec).update_user_app_metadata(
        user_id="auth0|abc", app_metadata={"tenant_id": "t1"}
    )
    assert user.user_id == "auth0|abc"


async def test_add_organization_member_request_shape(settings: Settings) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v2/organizations/org_123/members"
        assert _body(request) == {"members": ["auth0|abc"]}
        return httpx.Response(204)

    rec = _Recorder()
    rec.responder = responder
    result = await _client(settings, rec).add_organization_member(
        org_id="org_123", user_id="auth0|abc"
    )
    assert result is None


# ---------------------------------------------------------------------------
# Failure mapping
# ---------------------------------------------------------------------------


async def test_management_non_success_maps_to_typed_error(settings: Settings) -> None:
    rec = _Recorder()
    rec.responder = lambda r: httpx.Response(500, json={"error": "server"})
    with pytest.raises(Auth0ManagementError):
        await _client(settings, rec).create_organization(name="org-x", display_name="X")


async def test_transport_error_maps_to_typed_error(settings: Settings) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    rec = _Recorder()
    rec.responder = responder
    with pytest.raises(Auth0ManagementError):
        await _client(settings, rec).create_organization(name="org-x", display_name="X")


# ---------------------------------------------------------------------------
# Password-change ticket (Slice 2d-send)
# ---------------------------------------------------------------------------


async def test_create_password_change_ticket_request_and_parse(settings: Settings) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v2/tickets/password-change"
        assert _body(request) == {
            "user_id": "auth0|abc",
            "result_url": "https://app.sevyn8.com/welcome",
        }
        return httpx.Response(
            201, json={"ticket": "https://sevyn8.us.auth0.com/lo/reset?ticket=xyz"}
        )

    rec = _Recorder()
    rec.responder = responder
    url = await _client(settings, rec).create_password_change_ticket(
        user_id="auth0|abc", result_url="https://app.sevyn8.com/welcome"
    )
    assert url == "https://sevyn8.us.auth0.com/lo/reset?ticket=xyz"


async def test_create_password_change_ticket_missing_ticket_field(settings: Settings) -> None:
    rec = _Recorder()
    rec.responder = lambda r: httpx.Response(201, json={})  # no "ticket" key
    with pytest.raises(Auth0ManagementError):
        await _client(settings, rec).create_password_change_ticket(
            user_id="auth0|abc", result_url="https://app.sevyn8.com/welcome"
        )


async def test_create_password_change_ticket_non_success_maps_to_typed_error(
    settings: Settings,
) -> None:
    rec = _Recorder()
    rec.responder = lambda r: httpx.Response(400, json={"error": "bad"})
    with pytest.raises(Auth0ManagementError):
        await _client(settings, rec).create_password_change_ticket(
            user_id="auth0|abc", result_url="https://app.sevyn8.com/welcome"
        )
