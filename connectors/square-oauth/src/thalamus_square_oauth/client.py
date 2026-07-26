"""The Square OAuth HTTP client shared by the BFF (connect) and the connector (refresh).

Builds the ``/oauth2/authorize`` URL (offline) and calls ``/oauth2/token`` for the
``authorization_code`` exchange and the ``refresh_token`` grant. Scopes and environment are
per-app config stamped onto every stored token set. The client secret rides the request
body only; it is never logged and never placed in an error. Errors carry a bounded excerpt
of the vendor RESPONSE only.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx

from thalamus_square_oauth.errors import (
    SquareOAuthExchangeError,
    SquareOAuthRefreshRejectedError,
    SquareOAuthTransientError,
)
from thalamus_square_oauth.payload import SquareTokenSet

_EXCERPT_MAX_CHARS = 512

# The terminal (4xx) error to raise depends on the grant: exchange vs refresh.
_RejectError = SquareOAuthExchangeError | SquareOAuthRefreshRejectedError


def _excerpt(response: httpx.Response) -> str | None:
    text = response.text.strip()
    if not text:
        return None
    return text[:_EXCERPT_MAX_CHARS]


def _default_clock() -> datetime:
    return datetime.now(UTC)


class SquareOAuthClient:
    """Square OAuth operations. Vendor base URL selects sandbox vs production."""

    def __init__(
        self,
        *,
        base_url: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scopes: Sequence[str],
        environment: str,
        http: httpx.Client | None = None,
        clock: Callable[[], datetime] = _default_clock,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._scopes = tuple(scopes)
        self._environment = environment
        self._http = http or httpx.Client(timeout=30.0)
        self._clock = clock

    def authorize_url(self, *, state: str) -> str:
        """The seller-facing authorization URL. ``session=false`` per Square's guidance for
        production apps; scopes are space-joined; ``state`` is the caller's signed token."""
        params = {
            "client_id": self._client_id,
            "scope": " ".join(self._scopes),
            "state": state,
            "session": "false",
            "redirect_uri": self._redirect_uri,
        }
        return f"{self._base_url}/oauth2/authorize?{urlencode(params)}"

    def exchange_code(self, code: str) -> SquareTokenSet:
        """Exchange an authorization code for a token set (the connect path)."""
        body = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._redirect_uri,
        }
        return self._token_request(body, reject=SquareOAuthExchangeError)

    def refresh(self, refresh_token: str) -> SquareTokenSet:
        """Exchange a refresh token for a fresh access token (the connector read path).

        Code flow reuses the same refresh token, so the returned set carries it forward."""
        body = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        return self._token_request(body, reject=SquareOAuthRefreshRejectedError)

    def _token_request(
        self, body: dict[str, str], *, reject: type[_RejectError]
    ) -> SquareTokenSet:
        url = f"{self._base_url}/oauth2/token"
        try:
            response = self._http.post(url, json=body)
        except httpx.HTTPError as exc:
            raise SquareOAuthTransientError(
                f"Square token endpoint unreachable: {type(exc).__name__}"
            ) from exc
        status = response.status_code
        if status >= 500:
            raise SquareOAuthTransientError(
                f"Square token endpoint returned HTTP {status}", detail=_excerpt(response)
            )
        if status >= 400:
            # 4xx on a grant is terminal (bad code / revoked seller / invalid_grant).
            raise reject(f"Square rejected the token grant: HTTP {status}", detail=_excerpt(response))
        return self._to_token_set(response.json())

    def _to_token_set(self, data: dict[str, object]) -> SquareTokenSet:
        return SquareTokenSet(
            access_token=str(data["access_token"]),
            refresh_token=str(data["refresh_token"]),
            expires_at=str(data["expires_at"]),
            merchant_id=str(data["merchant_id"]),
            token_type=str(data.get("token_type") or "bearer"),
            scopes=self._scopes,
            obtained_at=self._clock().isoformat().replace("+00:00", "Z"),
            environment=self._environment,
        )
