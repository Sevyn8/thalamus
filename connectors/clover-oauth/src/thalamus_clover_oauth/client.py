"""The Clover OAuth HTTP client: authorize URL, code exchange, refresh, recovery.

Four legs, and the differences between them are load-bearing — each was confirmed against
the live Clover sandbox, and the vendor FAQ is wrong about at least one of them:

    GET  /oauth/v2/authorize   offline URL build. client_id + redirect_uri + state.
                               ``state`` IS supported and echoed back verbatim.
    POST /oauth/v2/token       client_id + client_secret + code
    POST /oauth/v2/refresh     client_id + refresh_token.  NO CLIENT SECRET on this leg.
    POST /oauth/v2/recovery    client_id + client_secret + recovery_token

EVERY POST IS JSON. Clover's token endpoints reject form-encoded bodies with HTTP 415; the
Clover FAQ claims both encodings are accepted and is WRONG (confirmed by a 415). ``httpx``'s
``json=`` is used throughout, which also means the client secret is serialised by
``json.dumps`` and never interpolated into a hand-built string (D7).

IDENTITY IS NOT IN ANY TOKEN RESPONSE. ``merchant_id`` and ``employee_id`` arrive on the
OAuth CALLBACK query string, not from ``/token``, so they are passed in by the caller and
carried forward across every rotation. That is why ``refresh`` and ``recover`` take them.

REFRESH IS DESTRUCTIVE. The moment Clover answers ``/oauth/v2/refresh``, the token that was
sent is dead and a NEW refresh token has replaced it. This client just reports that; the
persist-before-use ordering that makes it safe lives in ``token_store``.

Errors carry a bounded excerpt of the vendor RESPONSE only — never the request body.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx

from thalamus_clover_oauth.errors import (
    CloverOAuthError,
    CloverOAuthExchangeError,
    CloverOAuthRecoveryExhaustedError,
    CloverOAuthRefreshRejectedError,
    CloverOAuthTransientError,
)
from thalamus_clover_oauth.payload import CloverTokenSet

_EXCERPT_MAX_CHARS = 512

# Clover sets this on a refresh rejection to say whether the preceding token is still
# inside its recovery window. ADVISORY ONLY: the store never gates the recovery attempt on
# it (skipping a valid recovery costs the merchant; a needless attempt costs one HTTP call),
# but it is carried into the terminal error's detail because it is the single most useful
# datum when someone debugs a lost merchant months later.
RECOVERY_AVAILABLE_HEADER = "X-Clover-Recovery-Available"

# The sandbox host for region NA. Production is https://api.clover.com (per-region).
SANDBOX_BASE_URL = "https://sandbox.dev.clover.com"

_RejectError = (
    type[CloverOAuthExchangeError]
    | type[CloverOAuthRefreshRejectedError]
    | type[CloverOAuthRecoveryExhaustedError]
)


def _excerpt(response: httpx.Response) -> str | None:
    text = response.text.strip()
    if not text:
        return None
    return text[:_EXCERPT_MAX_CHARS]


def _detail_with_recovery_hint(response: httpx.Response) -> str | None:
    """The response excerpt, prefixed with the recovery-availability header when present."""
    header = response.headers.get(RECOVERY_AVAILABLE_HEADER)
    excerpt = _excerpt(response)
    if header is None:
        return excerpt
    hint = f"{RECOVERY_AVAILABLE_HEADER}={header}"
    return hint if excerpt is None else f"{hint}; {excerpt}"


def _default_clock() -> datetime:
    return datetime.now(UTC)


def environment_for(base_url: str) -> str:
    """``sandbox`` iff the host is a Clover sandbox host, else ``production``.

    Derived from the base URL rather than configured separately, mirroring how the Square
    lane resolves its environment stamp: one string decides both which host is called and
    what gets recorded on every stored record.
    """
    return "sandbox" if "sandbox" in base_url else "production"


class CloverOAuthClient:
    """Clover OAuth operations. The base URL selects sandbox vs production and region."""

    def __init__(
        self,
        *,
        base_url: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        http: httpx.Client | None = None,
        clock: Callable[[], datetime] = _default_clock,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._http = http or httpx.Client(timeout=30.0)
        self._clock = clock
        self._environment = environment_for(self._base_url)

    @property
    def environment(self) -> str:
        return self._environment

    def authorize_url(self, *, state: str) -> str:
        """The merchant-facing authorization URL.

        No ``scope`` parameter: Clover permissions are configured on the app in the
        dashboard, not requested per-authorize (which is why this package has no
        ``scopes`` module, unlike the Square lane).

        Two confirmed behaviours worth knowing before debugging this URL:
        a sub-path ``redirect_uri`` on the same base domain IS accepted; and if the app is
        NOT installed on the target merchant, Clover SILENTLY diverts to the App Market
        listing instead of erroring — so a callback that never arrives means "not
        installed", not "bad URL".
        """
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "state": state,
        }
        return f"{self._base_url}/oauth/v2/authorize?{urlencode(params)}"

    def exchange_code(self, code: str, *, merchant_id: str, employee_id: str | None) -> CloverTokenSet:
        """Exchange an authorization code for the first token record (the connect path).

        ``merchant_id`` / ``employee_id`` come from the callback query string, not from the
        response. The returned record has no ``previous_refresh_token``: nothing has been
        rotated out yet, so there is no recovery credential until the first refresh.
        """
        body = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code": code,
        }
        data = self._post("/oauth/v2/token", body, reject=CloverOAuthExchangeError)
        return self._to_token_set(data, merchant_id=merchant_id, employee_id=employee_id)

    def refresh(self, refresh_token: str, *, merchant_id: str, employee_id: str | None) -> CloverTokenSet:
        """Rotate the token pair. DESTRUCTIVE: on success ``refresh_token`` is now dead.

        Observed (2026-07-27, twice): the refresh token rotates on EVERY call — Clover never
        hands the same one back, unlike Square's code flow.

        No ``client_secret`` on this leg — Clover does not accept one here. The returned
        record does NOT yet carry ``previous_refresh_token``; the caller stamps the spent
        token via :meth:`CloverTokenSet.carrying_previous` before persisting, because only
        the caller knows which token it spent.
        """
        body = {"client_id": self._client_id, "refresh_token": refresh_token}
        data = self._post("/oauth/v2/refresh", body, reject=CloverOAuthRefreshRejectedError)
        return self._to_token_set(data, merchant_id=merchant_id, employee_id=employee_id)

    def recover(self, recovery_token: str, *, merchant_id: str, employee_id: str | None) -> CloverTokenSet:
        """Restore a rotated-away chain from the IMMEDIATELY PRECEDING refresh token.

        The window is roughly two weeks from when ``recovery_token`` was rotated out. A
        rejection here is terminal: the merchant must re-consent.
        """
        body = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "recovery_token": recovery_token,
        }
        data = self._post("/oauth/v2/recovery", body, reject=CloverOAuthRecoveryExhaustedError)
        return self._to_token_set(data, merchant_id=merchant_id, employee_id=employee_id)

    def _post(self, path: str, body: dict[str, str], *, reject: _RejectError) -> dict[str, object]:
        """POST a JSON body and classify the outcome. JSON only — form-encoding is a 415."""
        url = f"{self._base_url}{path}"
        try:
            response = self._http.post(url, json=body)
        except httpx.HTTPError as exc:
            raise CloverOAuthTransientError(
                f"Clover OAuth endpoint unreachable ({path}): {type(exc).__name__}"
            ) from exc
        status = response.status_code
        if status >= 500:
            raise CloverOAuthTransientError(
                f"Clover OAuth endpoint returned HTTP {status} ({path})",
                detail=_excerpt(response),
            )
        if status >= 400:
            # 4xx on any grant leg is terminal FOR THAT LEG. A 401 from /refresh is the
            # expected shape of a lost write, which the store answers with /recovery.
            raise reject(
                f"Clover rejected the grant: HTTP {status} ({path})",
                detail=_detail_with_recovery_hint(response),
            )
        payload: dict[str, object] = response.json()
        return payload

    def _to_token_set(
        self, data: dict[str, object], *, merchant_id: str, employee_id: str | None
    ) -> CloverTokenSet:
        """Map a Clover token response onto the stored record shape.

        Expiries are stored as the integer epoch seconds Clover sent, unconverted. A
        response missing either one is a contract break, not something to default: a
        silently-zero expiry would make every record look permanently expired.
        """
        try:
            access_expiration = int(data["access_token_expiration"])  # type: ignore[call-overload]
            refresh_expiration = int(data["refresh_token_expiration"])  # type: ignore[call-overload]
        except (KeyError, TypeError, ValueError) as exc:
            raise CloverOAuthError("Clover token response omitted or malformed an expiration field") from exc
        return CloverTokenSet(
            access_token=str(data["access_token"]),
            access_token_expiration=access_expiration,
            refresh_token=str(data["refresh_token"]),
            refresh_token_expiration=refresh_expiration,
            previous_refresh_token=None,  # stamped by the caller, which knows what it spent
            previous_rotated_at=None,
            merchant_id=merchant_id,
            employee_id=employee_id,
            obtained_at=int(self._clock().timestamp()),
            environment=self._environment,
        )
