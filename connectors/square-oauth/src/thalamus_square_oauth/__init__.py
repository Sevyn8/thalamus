"""Square OAuth + Secret Manager token vault, shared by the DIS BFF and the connector.

SDK-free by design (no ``thalamus_connector_sdk`` import), so the BFF can depend on it
without pulling the connector service graph. The connector runtime maps
``SquareOAuthRefreshRejected`` to the SDK-typed ``ConnectorAuthError(AUTH_FAILED)``.
"""

from __future__ import annotations

from thalamus_square_oauth.client import SquareOAuthClient
from thalamus_square_oauth.errors import (
    SquareOAuthError,
    SquareOAuthExchangeError,
    SquareOAuthRefreshRejectedError,
    SquareOAuthTransientError,
)
from thalamus_square_oauth.naming import secret_id_for
from thalamus_square_oauth.payload import SquareTokenSet
from thalamus_square_oauth.vault import GoogleSecretBackend, SecretBackend, SquareTokenVault

__all__ = [
    "GoogleSecretBackend",
    "SecretBackend",
    "SquareOAuthClient",
    "SquareOAuthError",
    "SquareOAuthExchangeError",
    "SquareOAuthRefreshRejectedError",
    "SquareOAuthTransientError",
    "SquareTokenSet",
    "SquareTokenVault",
    "secret_id_for",
]
