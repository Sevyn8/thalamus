"""SquareOAuthClient against httpx.MockTransport (no network): URL build, exchange, refresh."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from thalamus_square_oauth.client import SquareOAuthClient
from thalamus_square_oauth.errors import (
    SquareOAuthExchangeError,
    SquareOAuthRefreshRejectedError,
    SquareOAuthTransientError,
)

_BASE = "https://connect.squareupsandbox.test"
_SCOPES = ("MERCHANT_PROFILE_READ", "ITEMS_READ", "INVENTORY_READ", "ORDERS_READ")
_REDIRECT = "https://ui.test/connectors/square/callback"
_FIXED_NOW = datetime(2026, 7, 26, 12, 0, 0, tzinfo=UTC)

_TOKEN_JSON = {
    "access_token": "sq-access",
    "refresh_token": "sq-refresh",
    "expires_at": "2026-08-25T12:00:00Z",
    "merchant_id": "MERCH-1",
    "token_type": "bearer",
}


def _client(
    handler: httpx.MockTransport, *, secret: str = "app-secret", environment: str = "sandbox"
) -> SquareOAuthClient:
    return SquareOAuthClient(
        base_url=_BASE,
        client_id="app-id",
        client_secret=secret,
        redirect_uri=_REDIRECT,
        scopes=_SCOPES,
        environment=environment,
        http=httpx.Client(transport=handler),
        clock=lambda: _FIXED_NOW,
    )


def test_authorize_url_sandbox_omits_session() -> None:
    # Sandbox test sellers have no interactive login; session=false blanks the
    # authorize page, so it is omitted for sandbox.
    client = _client(httpx.MockTransport(lambda req: httpx.Response(200)))
    url = client.authorize_url(state="signed-state")
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == f"{_BASE}/oauth2/authorize"
    assert params["client_id"] == ["app-id"]
    assert params["scope"] == ["MERCHANT_PROFILE_READ ITEMS_READ INVENTORY_READ ORDERS_READ"]
    assert params["state"] == ["signed-state"]
    assert params["redirect_uri"] == [_REDIRECT]
    assert "session" not in params


def test_authorize_url_production_sets_session_false() -> None:
    # Production keeps session=false per Square's guidance (correct-account selection).
    client = _client(
        httpx.MockTransport(lambda req: httpx.Response(200)), environment="production"
    )
    params = parse_qs(urlparse(client.authorize_url(state="s")).query)
    assert params["session"] == ["false"]


def test_exchange_code_posts_authorization_code_and_stamps_scopes_env_clock() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_TOKEN_JSON)

    token_set = _client(httpx.MockTransport(handler)).exchange_code("auth-code")

    assert str(seen[0].url) == f"{_BASE}/oauth2/token"
    body = json.loads(seen[0].content)
    assert body["grant_type"] == "authorization_code"
    assert body["code"] == "auth-code"
    assert body["client_secret"] == "app-secret"
    assert token_set.access_token == "sq-access"
    assert token_set.refresh_token == "sq-refresh"
    assert token_set.scopes == _SCOPES
    assert token_set.environment == "sandbox"
    assert token_set.obtained_at == "2026-07-26T12:00:00Z"


def test_refresh_posts_refresh_token_and_carries_refresh_token_forward() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_TOKEN_JSON)

    token_set = _client(httpx.MockTransport(handler)).refresh("sq-refresh")

    body = json.loads(seen[0].content)
    assert body["grant_type"] == "refresh_token"
    assert body["refresh_token"] == "sq-refresh"
    assert token_set.refresh_token == "sq-refresh"


def test_exchange_4xx_raises_exchange_error_with_excerpt_and_no_secret_leak() -> None:
    handler = httpx.MockTransport(lambda req: httpx.Response(400, text="invalid authorization code"))
    with pytest.raises(SquareOAuthExchangeError) as exc_info:
        _client(handler, secret="TOP-SECRET").exchange_code("bad")
    assert exc_info.value.detail == "invalid authorization code"
    assert "TOP-SECRET" not in (exc_info.value.detail or "")


def test_refresh_4xx_raises_refresh_rejected() -> None:
    handler = httpx.MockTransport(lambda req: httpx.Response(401, text="invalid_grant"))
    with pytest.raises(SquareOAuthRefreshRejectedError) as exc_info:
        _client(handler).refresh("revoked")
    assert exc_info.value.detail == "invalid_grant"


def test_5xx_raises_transient() -> None:
    handler = httpx.MockTransport(lambda req: httpx.Response(503, text="unavailable"))
    with pytest.raises(SquareOAuthTransientError):
        _client(handler).refresh("rtok")


def test_network_error_raises_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with pytest.raises(SquareOAuthTransientError):
        _client(httpx.MockTransport(handler)).exchange_code("code")
