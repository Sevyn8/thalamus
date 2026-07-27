"""Clover OAuth + Secret Manager token vault and token store (Clover lane, slice C1).

SDK-free by design (no ``thalamus_connector_sdk`` import), so the BFF can depend on it
without pulling the connector service graph. The C2 connector maps this package's error
family onto SDK-typed errors on its own side.

Mirrors ``thalamus_square_oauth`` module-for-module where the concept exists. Three
differences, each forced by Clover rather than chosen:

- NO ``scopes`` module. Clover permissions are configured on the app in the dashboard, not
  requested on the authorize URL.
- Expiries are UNIX TIMESTAMPS, not RFC3339 strings.
- The TOKEN STORE lives here, not in the connector package: Clover refresh tokens are
  single-use, so persist-before-return is the whole point of the lane and had to exist
  before any connector did.
"""

from __future__ import annotations

from thalamus_clover_oauth.client import (
    RECOVERY_AVAILABLE_HEADER,
    SANDBOX_BASE_URL,
    CloverOAuthClient,
    environment_for,
)
from thalamus_clover_oauth.errors import (
    CloverOAuthError,
    CloverOAuthExchangeError,
    CloverOAuthNotConnectedError,
    CloverOAuthRecoveryExhaustedError,
    CloverOAuthRefreshRejectedError,
    CloverOAuthTransientError,
)
from thalamus_clover_oauth.naming import secret_id_for
from thalamus_clover_oauth.payload import (
    ACCESS_TOKEN_LIFETIME_SECONDS,
    REFRESH_TOKEN_LIFETIME_SECONDS,
    CloverTokenSet,
)
from thalamus_clover_oauth.token_store import (
    DEFAULT_REFRESH_SKEW,
    CloverSession,
    CloverTokenStore,
)
from thalamus_clover_oauth.vault import (
    KEEP_VERSIONS,
    CloverTokenVault,
    GoogleSecretBackend,
    SecretBackend,
)

__all__ = [
    "ACCESS_TOKEN_LIFETIME_SECONDS",
    "DEFAULT_REFRESH_SKEW",
    "KEEP_VERSIONS",
    "RECOVERY_AVAILABLE_HEADER",
    "REFRESH_TOKEN_LIFETIME_SECONDS",
    "SANDBOX_BASE_URL",
    "CloverOAuthClient",
    "CloverOAuthError",
    "CloverOAuthExchangeError",
    "CloverOAuthNotConnectedError",
    "CloverOAuthRecoveryExhaustedError",
    "CloverOAuthRefreshRejectedError",
    "CloverOAuthTransientError",
    "CloverSession",
    "CloverTokenSet",
    "CloverTokenStore",
    "CloverTokenVault",
    "GoogleSecretBackend",
    "SecretBackend",
    "environment_for",
    "secret_id_for",
]
