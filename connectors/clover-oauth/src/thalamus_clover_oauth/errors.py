"""The clover-oauth error family, rooted in ``dis_core`` ``DisError``.

Deliberately SDK-free: this package never imports ``thalamus_connector_sdk`` (whose
``__init__`` pulls the connector service graph), so the BFF can depend on it. The C2
connector runtime maps these to SDK-typed ``ConnectorAuthError`` / ``ConnectorExtractError``
on its own side, exactly as the Square lane does.

The vocabulary is the four outcomes a caller must be able to tell apart, plus two the
token store needs because — unlike Square — the store lives in this package:

    invalid_code           -> CloverOAuthExchangeError
    invalid_refresh_token  -> CloverOAuthRefreshRejectedError
    recovery_exhausted     -> CloverOAuthRecoveryExhaustedError   (TERMINAL: re-consent)
    vendor_unavailable     -> CloverOAuthTransientError           (retryable)
    (no stored record)     -> CloverOAuthNotConnectedError        (TERMINAL: first connect)

``CloverOAuthRefreshRejectedError`` is RECOVERABLE, not terminal: on the single-use
rotation model a rejected refresh usually means we rotated and lost the write, which is
what the recovery leg exists for. Only ``CloverOAuthRecoveryExhaustedError`` means the
merchant is genuinely lost and must re-consent.

``detail`` carries a bounded excerpt of the vendor RESPONSE only — never the request body
(which holds the client secret on two of the three legs) and never a token value.
"""

from __future__ import annotations

from dis_core.errors import DisError


class CloverOAuthError(DisError):
    """Base for clover-oauth failures."""

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class CloverOAuthExchangeError(CloverOAuthError):
    """The authorization_code exchange was rejected by Clover (non-retryable 4xx).

    Usually a spent or expired code, or a redirect_uri that does not match the app's
    registered value. NOT recoverable: restart the authorize leg.
    """


class CloverOAuthRefreshRejectedError(CloverOAuthError):
    """A ``/oauth/v2/refresh`` grant was rejected (typically HTTP 401).

    On Clover's SINGLE-USE rotation model this most often means our stored refresh token
    was already spent — i.e. we rotated and lost the persist. The token store answers this
    by attempting ``/oauth/v2/recovery`` with ``previous_refresh_token`` (D4); it is only
    terminal once that also fails.
    """


class CloverOAuthRecoveryExhaustedError(CloverOAuthError):
    """TERMINAL: the merchant must re-consent. No further automated path exists.

    Raised when the recovery leg cannot restore the chain, which covers three cases the
    operator sees identically (all need a fresh authorize):

    - ``/oauth/v2/recovery`` was attempted with ``previous_refresh_token`` and rejected
      (past the ~2-week window, or that token was itself already consumed);
    - the stored record carries no ``previous_refresh_token`` to recover with;
    - the stored refresh token is past ``refresh_token_expiration`` (~1 year), so neither
      leg can succeed and no network call is worth making.

    Where Clover sent ``X-Clover-Recovery-Available``, its value is carried in ``detail``:
    it is the single most useful datum when debugging a lost merchant after the fact.
    """


class CloverOAuthTransientError(CloverOAuthError):
    """A transient failure calling a Clover OAuth endpoint (5xx / network). Retryable."""


class CloverOAuthNotConnectedError(CloverOAuthError):
    """TERMINAL: no stored token record for this (tenant, source).

    Distinct from :class:`CloverOAuthRecoveryExhaustedError` on purpose. Both need an
    authorize leg, but this one means the merchant never onboarded, while recovery-exhausted
    means DIS held a working chain and lost it — a materially different thing to find in a
    log, and the second warrants investigating why.
    """
