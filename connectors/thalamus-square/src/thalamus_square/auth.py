"""Per-tenant/source Square access-token resolution.

``TokenStore`` is the seam the adapter drives to get a valid Square access token for a
``(tenant_id, source_id)`` key. Three implementations:

- ``VaultTokenStore`` (production): reads the OAuth token set from the Secret Manager vault
  (``thalamus_square_oauth``), refreshes it when near expiry, persists the rotated set, and
  returns the access token. This is the S2 production default.
- ``EnvTokenStore`` (dev / the operator sandbox smoke script): a single
  ``SQUARE_ACCESS_TOKEN`` for every tenant/source, no OAuth vault.
- ``FakeTokenStore`` (offline tests) lives in ``fakes.py``.

The token is credential material: never logged, never placed in audit or error context.
The tenant/source identifiers ARE safe to carry in error context.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from thalamus_connector_sdk import ConnectorAuthError, ConnectorExtractError, ConnectorReasonCode
from thalamus_square_oauth import (
    SquareOAuthClient,
    SquareOAuthRefreshRejectedError,
    SquareOAuthTransientError,
    SquareTokenVault,
)

_SQUARE_ACCESS_TOKEN = "SQUARE_ACCESS_TOKEN"


class TokenStore(Protocol):
    """Yields a tenant/source's Square access token, or raises ``ConnectorAuthError``."""

    def get_token(self, tenant_id: UUID, source_id: str) -> str: ...


class EnvTokenStore:
    """Dev / smoke-script fallback: a single ``SQUARE_ACCESS_TOKEN`` for every tenant/source
    (sandbox only). Not the production path — that is :class:`VaultTokenStore`."""

    def get_token(self, tenant_id: UUID, source_id: str) -> str:
        token = os.environ.get(_SQUARE_ACCESS_TOKEN)
        if not token:
            raise ConnectorAuthError(
                f"{_SQUARE_ACCESS_TOKEN} is not set; cannot authenticate to Square",
                reason=ConnectorReasonCode.AUTH_FAILED,
                tenant_id=str(tenant_id),
            )
        return token


def _utcnow() -> datetime:
    return datetime.now(UTC)


class VaultTokenStore:
    """Secret Manager-backed token store (the S2 production default).

    On each read: fetch the stored token set for ``(tenant, source)``; if it is within the
    refresh skew of expiry, refresh via Square (code flow reuses the same refresh token) and
    persist the rotated set; return the access token. A rejected refresh (revoked seller /
    invalid_grant) surfaces as ``ConnectorAuthError(AUTH_FAILED)``; a transient token-endpoint
    failure surfaces as ``ConnectorExtractError(VENDOR_UNAVAILABLE)``.

    Concurrency: no lock. Code-flow refresh reuses the same refresh token, so concurrent
    refreshes are idempotent w.r.t. it; ``AddSecretVersion`` is atomic and any stored latest
    version carries a valid access token plus the stable refresh token, so last-writer-wins
    is safe (the cheapest sound option).
    """

    def __init__(
        self,
        *,
        vault: SquareTokenVault,
        client: SquareOAuthClient,
        refresh_skew: timedelta,
    ) -> None:
        self._vault = vault
        self._client = client
        self._refresh_skew = refresh_skew

    def get_token(self, tenant_id: UUID, source_id: str) -> str:
        current = self._vault.read(tenant_id, source_id)
        if current is None:
            raise ConnectorAuthError(
                "no Square OAuth token for this source; the tenant has not connected Square",
                reason=ConnectorReasonCode.AUTH_FAILED,
                tenant_id=str(tenant_id),
            )
        if not current.needs_refresh(now=_utcnow(), skew=self._refresh_skew):
            return current.access_token
        try:
            refreshed = self._client.refresh(current.refresh_token)
        except SquareOAuthRefreshRejectedError as exc:
            raise ConnectorAuthError(
                "Square rejected the refresh; the seller may have revoked access",
                reason=ConnectorReasonCode.AUTH_FAILED,
                tenant_id=str(tenant_id),
            ) from exc
        except SquareOAuthTransientError as exc:
            raise ConnectorExtractError(
                "Square token endpoint was unavailable during refresh",
                reason=ConnectorReasonCode.VENDOR_UNAVAILABLE,
                tenant_id=str(tenant_id),
            ) from exc
        self._vault.write(tenant_id, source_id, refreshed)
        return refreshed.access_token
