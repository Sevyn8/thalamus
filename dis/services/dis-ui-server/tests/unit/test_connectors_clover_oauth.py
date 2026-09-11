"""Clover OAuth connect endpoints + the shared signed state (unit; fakes, no network).

The app is built through the production factory (conftest ``client`` fixture); the OAuth
dependencies are set on ``app.state`` as fakes after startup, mirroring the Square suite.

Two things here are Clover-specific and are the reason the handler is duplicated rather
than generalised (D5): the exchange is JSON-only, and the merchant id arrives in the REQUEST
BODY because Clover's token response does not carry one.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dis_ui_server.oauth.state import sign_state, verify_state
from thalamus_clover_oauth import CloverOAuthClient, CloverTokenSet, CloverTokenVault

_TENANT_A = "019f9d6d-c032-7e03-a232-ee77299f9b5d"
_TENANT_B = "019e5e3c-b5d6-7eed-93f9-3778a7a7a160"
_STATE_KEY = "test-state-signing-key"
_SOURCE = "clover_pos_v1"
_MERCHANT = "0RKKDBMKPAH71"
_AUTHZ_URL = "/api/v1/connectors/clover/oauth/authorize-url"
_COMPLETE_URL = "/api/v1/connectors/clover/oauth/complete"

# Clover's token response: UNIX-timestamp expiries, and NO merchant id.
_TOKEN_JSON = {
    "access_token": "clv-access-secret",
    "access_token_expiration": 1_785_000_000,
    "refresh_token": "clvroar-refresh-secret",
    "refresh_token_expiration": 1_816_000_000,
}


class _FakeBackend:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def access_latest(self, secret_id: str) -> bytes | None:
        return self.store.get(secret_id)

    def add_version(self, secret_id: str, data: bytes) -> None:
        self.store[secret_id] = data

    def list_enabled_versions(self, secret_id: str) -> list[str]:
        return []

    def destroy_version(self, version_name: str) -> None:  # pragma: no cover - never reached
        raise AssertionError("no versions to prune in these tests")


def _configure(client: TestClient, handler: httpx.MockTransport) -> CloverTokenVault:
    """Wire fake OAuth deps onto the running app; return the vault for assertions."""
    clover_client = CloverOAuthClient(
        base_url="https://sandbox.dev.clover.test",
        client_id="T4RKJYVE63ARA",
        client_secret="app-secret",
        redirect_uri="https://ui.test/connectors/clover/callback",
        http=httpx.Client(transport=handler),
    )
    vault = CloverTokenVault(_FakeBackend())
    app = cast(FastAPI, client.app)
    app.state.clover_oauth_client = clover_client
    app.state.clover_token_vault = vault
    app.state.oauth_state_key = _STATE_KEY
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


def _body(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "code": "auth-code",
        "state": _signed_state(_TENANT_A),
        "merchant_id": _MERCHANT,
    }
    base.update(over)
    return base


# ----- authorize-url -----


def test_authorize_url_unconfigured_returns_503(client: TestClient, mint_token: Callable[..., str]) -> None:
    resp = client.get(_AUTHZ_URL, params={"source_id": _SOURCE}, headers=_auth(mint_token()))
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "oauth_not_configured"


def test_authorize_url_round_trips_the_state(client: TestClient, mint_token: Callable[..., str]) -> None:
    _configure(client, _ok_handler())
    resp = client.get(
        _AUTHZ_URL, params={"source_id": _SOURCE}, headers=_auth(mint_token(tenant_id=_TENANT_A))
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Clover requests no scopes on the URL: permissions live on the app, not the grant.
    assert "scope" not in body["authorize_url"]
    assert "/oauth/v2/authorize" in body["authorize_url"]
    payload = verify_state(body["state"], key=_STATE_KEY)
    assert str(payload.tenant_id) == _TENANT_A
    assert payload.source_id == _SOURCE


def test_authorize_url_no_auth_returns_401(client: TestClient) -> None:
    assert client.get(_AUTHZ_URL, params={"source_id": _SOURCE}).status_code == 401


# ----- complete -----


def test_complete_exchanges_and_persists_with_the_body_merchant(
    client: TestClient, mint_token: Callable[..., str]
) -> None:
    vault = _configure(client, _ok_handler())
    resp = client.post(_COMPLETE_URL, json=_body(), headers=_auth(mint_token(tenant_id=_TENANT_A)))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "connector": "clover",
        "status": "connected",
        "source_id": _SOURCE,
        "merchant_id": _MERCHANT,
    }
    # THE Clover-specific bit: the merchant is not in the token response, so it can only
    # have reached the stored record from the request body.
    stored = vault.read(UUID(_TENANT_A), _SOURCE)
    assert stored is not None
    assert stored.merchant_id == _MERCHANT
    assert stored.access_token == "clv-access-secret"


def test_complete_posts_json_not_form(client: TestClient, mint_token: Callable[..., str]) -> None:
    # Clover's token endpoint 415s on form-encoded; the FAQ claims otherwise and is wrong.
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_TOKEN_JSON)

    _configure(client, httpx.MockTransport(handler))
    client.post(_COMPLETE_URL, json=_body(), headers=_auth(mint_token(tenant_id=_TENANT_A)))
    assert seen[0].headers["content-type"] == "application/json"


def test_complete_rejects_a_state_for_another_tenant(
    client: TestClient, mint_token: Callable[..., str]
) -> None:
    # The state is the authority for which tenant the tokens belong to; a TENANT caller may
    # only act for its own. The mismatched tenant id is never echoed back.
    _configure(client, _ok_handler())
    resp = client.post(
        _COMPLETE_URL,
        json=_body(state=_signed_state(_TENANT_B)),
        headers=_auth(mint_token(tenant_id=_TENANT_A)),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "oauth_state_tenant_mismatch"
    assert _TENANT_B not in resp.text


def test_complete_rejects_a_forged_state(client: TestClient, mint_token: Callable[..., str]) -> None:
    _configure(client, _ok_handler())
    forged = sign_state(
        tenant_id=UUID(_TENANT_A),
        source_id=_SOURCE,
        key="not-the-server-key",
        nonce="n",
        now=datetime.now(UTC),
        ttl=timedelta(minutes=10),
    )
    resp = client.post(
        _COMPLETE_URL, json=_body(state=forged), headers=_auth(mint_token(tenant_id=_TENANT_A))
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_oauth_state"


def test_complete_rejects_an_expired_state(client: TestClient, mint_token: Callable[..., str]) -> None:
    _configure(client, _ok_handler())
    expired = sign_state(
        tenant_id=UUID(_TENANT_A),
        source_id=_SOURCE,
        key=_STATE_KEY,
        nonce="n",
        now=datetime.now(UTC) - timedelta(hours=1),
        ttl=timedelta(minutes=10),
    )
    resp = client.post(
        _COMPLETE_URL, json=_body(state=expired), headers=_auth(mint_token(tenant_id=_TENANT_A))
    )
    assert resp.status_code == 422


def test_complete_requires_a_merchant_id(client: TestClient, mint_token: Callable[..., str]) -> None:
    # Without it the stored record could never address /v3/merchants/{mId}/... at all.
    _configure(client, _ok_handler())
    body = _body()
    del body["merchant_id"]
    resp = client.post(_COMPLETE_URL, json=body, headers=_auth(mint_token(tenant_id=_TENANT_A)))
    assert resp.status_code == 422


def test_complete_maps_a_vendor_failure_to_502_without_vendor_detail(
    client: TestClient, mint_token: Callable[..., str]
) -> None:
    handler = httpx.MockTransport(
        lambda req: httpx.Response(400, json={"message": "clover internals leaked"})
    )
    _configure(client, handler)
    resp = client.post(_COMPLETE_URL, json=_body(), headers=_auth(mint_token(tenant_id=_TENANT_A)))
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "clover_token_exchange"
    assert "clover internals leaked" not in resp.text


def test_complete_persists_nothing_when_the_exchange_fails(
    client: TestClient, mint_token: Callable[..., str]
) -> None:
    vault = _configure(client, httpx.MockTransport(lambda req: httpx.Response(400, json={})))
    client.post(_COMPLETE_URL, json=_body(), headers=_auth(mint_token(tenant_id=_TENANT_A)))
    assert vault.read(UUID(_TENANT_A), _SOURCE) is None


def test_complete_unconfigured_returns_503(client: TestClient, mint_token: Callable[..., str]) -> None:
    resp = client.post(_COMPLETE_URL, json=_body(), headers=_auth(mint_token(tenant_id=_TENANT_A)))
    assert resp.status_code == 503


# ----- the shared state key -----


def test_clover_works_when_square_oauth_is_unconfigured(
    client: TestClient, mint_token: Callable[..., str]
) -> None:
    """THE reason the state key moved out of the Square branch.

    Square's client/vault are left None (unconfigured), which is the default for this
    fixture. Clover must still connect: the state key is a SHARED primitive, and one
    vendor's missing config must never disable another vendor's connect flow.
    """
    _configure(client, _ok_handler())
    app = cast(FastAPI, client.app)
    app.state.square_oauth_client = None
    app.state.square_token_vault = None
    app.state.square_oauth_state_key = None

    resp = client.post(_COMPLETE_URL, json=_body(), headers=_auth(mint_token(tenant_id=_TENANT_A)))
    assert resp.status_code == 200, resp.text


def test_a_square_state_verifies_for_clover_because_the_key_is_shared() -> None:
    # Not a vulnerability: the state binds (tenant, source), and the source is what routes
    # the write. One key, one secret, every vendor - the mechanism is vendor-agnostic and
    # each vendor echoes `state` back verbatim.
    token = sign_state(
        tenant_id=UUID(_TENANT_A),
        source_id="square_pos_v2",
        key=_STATE_KEY,
        nonce="n",
        now=datetime.now(UTC),
        ttl=timedelta(minutes=10),
    )
    payload = verify_state(token, key=_STATE_KEY)
    assert payload.source_id == "square_pos_v2"


def test_the_stored_record_is_a_clover_token_set(client: TestClient, mint_token: Callable[..., str]) -> None:
    # Unix-timestamp expiries, not Square's RFC3339 strings.
    vault = _configure(client, _ok_handler())
    client.post(_COMPLETE_URL, json=_body(), headers=_auth(mint_token(tenant_id=_TENANT_A)))
    stored = vault.read(UUID(_TENANT_A), _SOURCE)
    assert isinstance(stored, CloverTokenSet)
    assert stored.access_token_expiration == 1_785_000_000
    assert stored.previous_refresh_token is None  # nothing rotated out on a first connect
