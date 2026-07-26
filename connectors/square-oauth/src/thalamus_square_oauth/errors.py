"""The square-oauth error family, rooted in ``dis_core`` ``DisError``.

Deliberately SDK-free: this package never imports ``thalamus_connector_sdk`` (whose
``__init__`` pulls the connector service graph), so the BFF can depend on it. The
connector runtime maps :class:`SquareOAuthRefreshRejected` to the SDK-typed
``ConnectorAuthError(AUTH_FAILED)`` on its own side.

``detail`` carries a bounded excerpt of the vendor RESPONSE only, never the request body
(which holds the client secret) and never a token value.
"""

from __future__ import annotations

from dis_core.errors import DisError


class SquareOAuthError(DisError):
    """Base for square-oauth failures."""

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class SquareOAuthExchangeError(SquareOAuthError):
    """The authorization_code exchange was rejected by Square (non-retryable 4xx)."""


class SquareOAuthRefreshRejectedError(SquareOAuthError):
    """A refresh_token grant was rejected (revoked seller / invalid_grant). Non-retryable;
    the connector maps this to ConnectorAuthError(AUTH_FAILED)."""


class SquareOAuthTransientError(SquareOAuthError):
    """A transient failure calling Square's token endpoint (5xx / network). Retryable."""
