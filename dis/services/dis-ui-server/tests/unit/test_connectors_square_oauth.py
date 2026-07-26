"""Square OAuth connect endpoints + the signed-state signer (unit; fakes, no network).

The app is built through the production factory (conftest ``client`` fixture); the OAuth
dependencies are set on ``app.state`` as fakes after startup (a SquareOAuthClient over
httpx.MockTransport + a SquareTokenVault over an in-memory backend + a test state key),
mirroring how the other backends are faked. Tokens are minted with the dev-stub params.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dis_ui_server.config import SQUARE_SANDBOX_OAUTH_BASE_URL, UiServerConfig
from dis_ui_server.oauth.errors import InvalidOauthStateError
from dis_ui_server.oauth.state import sign_state, verify_state
from thalamus_square_oauth import SQUARE_READ_SCOPES, SquareOAuthClient, SquareTokenVault

_TENANT_A = "019e5e3c-b5d3-705f-9002-2451c4ca2626"
_TENANT_B = "019e5e3c-b5d6-7eed-93f9-3778a7a7a160"
_STATE_KEY = "test-state-signing-key"
_SOURCE = "square-prod"
_AUTHZ_URL = "/api/v1/connectors/square/oauth/authorize-url"
_COMPLETE_URL = "/api/v1/connectors/square/oauth/complete"

_TOKEN_JSON = {
    "access_token": "sq-access-secret",
    "refresh_token": "sq-refresh-secret",
    "expires_at": "2026-08-25T12:00:00Z",
    "merchant_id": "MERCH-42",
    "token_type": "bearer",
}


class _FakeBackend:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def access_latest(self, secret_id: str) -> bytes | None:
        return self.store.get(secret_id)

    def add_version(self, secret_id: str, data: bytes) -> None:
        self.store[secret_id] = data


def _configure(client: TestClient, handler: httpx.MockTransport) -> SquareTokenVault:
    """Wire fake OAuth deps onto the running app; return the vault for assertions."""
    square_client = SquareOAuthClient(
        base_url="https://connect.squareupsandbox.test",
        client_id="app-id",
        client_secret="app-secret",
        redirect_uri="https://ui.test/connectors/square/callback",
        scopes=SQUARE_READ_SCOPES,
        environment="sandbox",
        http=httpx.Client(transport=handler),
    )
    vault = SquareTokenVault(_FakeBackend())
    app = cast(FastAPI, client.app)
    app.state.square_oauth_client = square_client
    app.state.square_token_vault = vault
    app.state.square_oauth_state_key = _STATE_KEY
    return vault


def _ok_handler() -> httpx.MockTransport:
    return httpx.MockTransport(lambda req: httpx.Response(200, json=_TOKEN_JSON))


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _signed_state(tenant_id: str, source_id: str = _SOURCE) -> str:

    return sign_state(
        tenant_id=UUID(tenant_id),
        source_id=source_id,
        key=_STATE_KEY,
        nonce="nonce-1",
        now=datetime.now(UTC),
        ttl=timedelta(minutes=10),
    )


# ----- authorize-url -----


def test_authorize_url_unconfigured_returns_503(client: TestClient, mint_token: Callable[..., str]) -> None:
    resp = client.get(_AUTHZ_URL, params={"source_id": _SOURCE}, headers=_auth(mint_token()))
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "oauth_not_configured"


def test_authorize_url_happy_tenant(client: TestClient, mint_token: Callable[..., str]) -> None:
    _configure(client, _ok_handler())
    resp = client.get(
        _AUTHZ_URL, params={"source_id": _SOURCE}, headers=_auth(mint_token(tenant_id=_TENANT_A))
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "MERCHANT_PROFILE_READ" in body["authorize_url"]
    assert "ORDERS_READ" in body["authorize_url"]
    # The returned state decodes to the caller's tenant + the requested source.
    payload = verify_state(body["state"], key=_STATE_KEY)
    assert str(payload.tenant_id) == _TENANT_A
    assert payload.source_id == _SOURCE


def test_authorize_url_no_auth_returns_401(client: TestClient) -> None:
    assert client.get(_AUTHZ_URL, params={"source_id": _SOURCE}).status_code == 401


# ----- complete -----


def test_complete_happy_exchanges_and_persists(client: TestClient, mint_token: Callable[..., str]) -> None:
    vault = _configure(client, _ok_handler())
    state = _signed_state(_TENANT_A)
    resp = client.post(
        _COMPLETE_URL,
        json={"code": "auth-code", "state": state},
        headers=_auth(mint_token(tenant_id=_TENANT_A)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "connector": "square",
        "status": "connected",
        "source_id": _SOURCE,
        "merchant_id": "MERCH-42",
    }

    persisted = vault.read(UUID(_TENANT_A), _SOURCE)
    assert persisted is not None
    assert persisted.access_token == "sq-access-secret"  # token set was written to the vault


def test_complete_bad_state_returns_422_without_exchange(
    client: TestClient, mint_token: Callable[..., str]
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_TOKEN_JSON)

    _configure(client, httpx.MockTransport(handler))
    resp = client.post(
        _COMPLETE_URL,
        json={"code": "c", "state": "not-a-valid-jwt"},
        headers=_auth(mint_token(tenant_id=_TENANT_A)),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_oauth_state"
    assert calls == []  # never reached the token exchange


def test_complete_state_tenant_mismatch_returns_403(
    client: TestClient, mint_token: Callable[..., str]
) -> None:
    _configure(client, _ok_handler())
    state = _signed_state(_TENANT_A)  # state binds tenant A
    resp = client.post(  # caller is tenant B
        _COMPLETE_URL, json={"code": "c", "state": state}, headers=_auth(mint_token(tenant_id=_TENANT_B))
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "oauth_state_tenant_mismatch"


def test_complete_exchange_failure_returns_502_and_does_not_persist(
    client: TestClient, mint_token: Callable[..., str]
) -> None:
    vault = _configure(client, httpx.MockTransport(lambda req: httpx.Response(400, text="bad code")))
    state = _signed_state(_TENANT_A)
    resp = client.post(
        _COMPLETE_URL, json={"code": "bad", "state": state}, headers=_auth(mint_token(tenant_id=_TENANT_A))
    )
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "square_token_exchange"

    assert vault.read(UUID(_TENANT_A), _SOURCE) is None  # nothing written on failure


def test_complete_never_logs_tokens(
    client: TestClient, mint_token: Callable[..., str], caplog: pytest.LogCaptureFixture
) -> None:
    _configure(client, _ok_handler())
    state = _signed_state(_TENANT_A)
    with caplog.at_level("DEBUG"):
        client.post(
            _COMPLETE_URL, json={"code": "c", "state": state}, headers=_auth(mint_token(tenant_id=_TENANT_A))
        )
    assert "sq-access-secret" not in caplog.text
    assert "sq-refresh-secret" not in caplog.text


# ----- state signer (pure) -----


def test_state_round_trips() -> None:

    token = sign_state(
        tenant_id=UUID(_TENANT_A),
        source_id=_SOURCE,
        key=_STATE_KEY,
        nonce="n",
        now=datetime.now(UTC),
        ttl=timedelta(minutes=10),
    )
    payload = verify_state(token, key=_STATE_KEY)
    assert str(payload.tenant_id) == _TENANT_A
    assert payload.source_id == _SOURCE


def test_state_tampered_key_rejected() -> None:
    token = _signed_state(_TENANT_A)
    with pytest.raises(InvalidOauthStateError):
        verify_state(token, key="wrong-key")


def test_state_expired_rejected() -> None:

    token = sign_state(
        tenant_id=UUID(_TENANT_A),
        source_id=_SOURCE,
        key=_STATE_KEY,
        nonce="n",
        now=datetime.now(UTC) - timedelta(hours=1),
        ttl=timedelta(minutes=10),
    )
    with pytest.raises(InvalidOauthStateError):
        verify_state(token, key=_STATE_KEY)


# ----- config -----


def _base_config(**overrides: object) -> UiServerConfig:
    fields: dict[str, object] = {
        "postgres_url": "postgresql+psycopg://u:p@127.0.0.1:9/ithina_dis_db",
        "gcs_bucket_bronze": "b",
        "pubsub_project_id": "proj",
    }
    fields.update(overrides)
    return UiServerConfig(**fields)  # type: ignore[arg-type]


def test_config_oauth_unconfigured_by_default() -> None:
    assert _base_config().square_oauth_configured is False


def test_config_oauth_configured_when_all_present() -> None:
    config = _base_config(
        square_client_id="id",
        square_app_secret="secret",
        square_oauth_redirect_uri="https://ui.test/cb",
        square_oauth_state_key="key",
    )
    assert config.square_oauth_configured is True
    assert config.square_oauth_base_url == SQUARE_SANDBOX_OAUTH_BASE_URL
    assert config.square_oauth_environment == "sandbox"
