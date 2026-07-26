"""VaultTokenStore: read, refresh-on-near-expiry, persist, and typed AUTH_FAILED mapping.

No network: a real SquareTokenVault over an in-memory backend + a real SquareOAuthClient
over httpx.MockTransport. Expiries are relative to the real clock so the fresh vs
near-expiry branches are deterministic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest

from thalamus_connector_sdk import ConnectorAuthError, ConnectorExtractError, ConnectorReasonCode
from thalamus_square.auth import VaultTokenStore
from thalamus_square_oauth import SquareOAuthClient, SquareTokenSet, SquareTokenVault

_TENANT = UUID("019e5e3c-b5d3-705f-9002-2451c4ca2626")
_SOURCE = "square-prod"
_SKEW = timedelta(days=3)


class _FakeBackend:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def access_latest(self, secret_id: str) -> bytes | None:
        return self.store.get(secret_id)

    def add_version(self, secret_id: str, data: bytes) -> None:
        self.store[secret_id] = data


def _token_set(*, access: str, expires_at: datetime, refresh: str = "rtok") -> SquareTokenSet:
    return SquareTokenSet(
        access_token=access,
        refresh_token=refresh,
        expires_at=expires_at.isoformat().replace("+00:00", "Z"),
        merchant_id="M1",
        token_type="bearer",
        scopes=("ITEMS_READ",),
        obtained_at="2026-07-01T00:00:00Z",
        environment="sandbox",
    )


def _store(vault: SquareTokenVault, handler: httpx.MockTransport) -> VaultTokenStore:
    client = SquareOAuthClient(
        base_url="https://connect.squareupsandbox.test",
        client_id="app-id",
        client_secret="app-secret",
        redirect_uri="",
        scopes=("ITEMS_READ",),
        environment="sandbox",
        http=httpx.Client(transport=handler),
    )
    return VaultTokenStore(vault=vault, client=client, refresh_skew=_SKEW)


def _no_calls() -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(500)  # must not be reached in the fresh-token case

    return httpx.MockTransport(handler), seen


def test_fresh_token_returned_without_refresh() -> None:
    vault = SquareTokenVault(_FakeBackend())
    fresh = _token_set(access="fresh", expires_at=datetime.now(UTC) + timedelta(days=30))
    vault.write(_TENANT, _SOURCE, fresh)
    handler, seen = _no_calls()

    token = _store(vault, handler).get_token(_TENANT, _SOURCE)

    assert token == "fresh"
    assert seen == []  # no token-endpoint call when the access token is not near expiry


def test_near_expiry_refreshes_persists_and_returns_new_token() -> None:
    vault = SquareTokenVault(_FakeBackend())
    vault.write(_TENANT, _SOURCE, _token_set(access="old", expires_at=datetime.now(UTC) + timedelta(hours=1)))
    refreshed_json = {
        "access_token": "new-access",
        "refresh_token": "rtok",
        "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        "merchant_id": "M1",
        "token_type": "bearer",
    }
    handler = httpx.MockTransport(lambda req: httpx.Response(200, json=refreshed_json))

    token = _store(vault, handler).get_token(_TENANT, _SOURCE)

    assert token == "new-access"
    persisted = vault.read(_TENANT, _SOURCE)
    assert persisted is not None
    assert persisted.access_token == "new-access"  # rotated set was written back


def test_missing_secret_raises_auth_failed() -> None:
    vault = SquareTokenVault(_FakeBackend())  # nothing stored
    handler, _ = _no_calls()
    with pytest.raises(ConnectorAuthError) as exc_info:
        _store(vault, handler).get_token(_TENANT, _SOURCE)
    assert exc_info.value.reason is ConnectorReasonCode.AUTH_FAILED
    assert exc_info.value.tenant_id == str(_TENANT)


def test_refresh_rejected_raises_auth_failed() -> None:
    vault = SquareTokenVault(_FakeBackend())
    vault.write(_TENANT, _SOURCE, _token_set(access="old", expires_at=datetime.now(UTC) + timedelta(hours=1)))
    handler = httpx.MockTransport(lambda req: httpx.Response(401, text="invalid_grant"))
    with pytest.raises(ConnectorAuthError) as exc_info:
        _store(vault, handler).get_token(_TENANT, _SOURCE)
    assert exc_info.value.reason is ConnectorReasonCode.AUTH_FAILED
    assert exc_info.value.tenant_id == str(_TENANT)


def test_refresh_transient_raises_vendor_unavailable() -> None:
    vault = SquareTokenVault(_FakeBackend())
    vault.write(_TENANT, _SOURCE, _token_set(access="old", expires_at=datetime.now(UTC) + timedelta(hours=1)))
    handler = httpx.MockTransport(lambda req: httpx.Response(503, text="unavailable"))
    with pytest.raises(ConnectorExtractError) as exc_info:
        _store(vault, handler).get_token(_TENANT, _SOURCE)
    assert exc_info.value.reason is ConnectorReasonCode.VENDOR_UNAVAILABLE
