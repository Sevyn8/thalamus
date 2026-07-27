"""CloverOAuthClient against httpx.MockTransport (no network).

Covers the four legs and the three vendor behaviours that were confirmed empirically and
that documentation gets wrong: JSON-only bodies, no client_secret on the refresh leg, and
`state` echoed on the authorize URL.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from thalamus_clover_oauth.client import (
    RECOVERY_AVAILABLE_HEADER,
    CloverOAuthClient,
    environment_for,
)
from thalamus_clover_oauth.errors import (
    CloverOAuthError,
    CloverOAuthExchangeError,
    CloverOAuthRecoveryExhaustedError,
    CloverOAuthRefreshRejectedError,
    CloverOAuthTransientError,
)

_BASE = "https://sandbox.dev.clover.com"
_REDIRECT = "https://ui.test/connectors/clover/callback"
_FIXED_NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
_MERCHANT = "0RKKDBMKPAH71"

_TOKEN_JSON = {
    "access_token": "eyJhbGciOi.access.jwt",
    "access_token_expiration": 1_785_000_000,
    "refresh_token": "clvroar-new",
    "refresh_token_expiration": 1_816_000_000,
}


def _client(handler: httpx.MockTransport, *, secret: str = "app-secret") -> CloverOAuthClient:
    return CloverOAuthClient(
        base_url=_BASE,
        client_id="T4RKJYVE63ARA",
        client_secret=secret,
        redirect_uri=_REDIRECT,
        http=httpx.Client(transport=handler),
        clock=lambda: _FIXED_NOW,
    )


def _capture(
    status: int = 200, body: object = None, headers: dict[str, str] | None = None
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    """A MockTransport that records every request and returns one canned response."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body if body is not None else _TOKEN_JSON, headers=headers)

    return httpx.MockTransport(handler), seen


# -- authorize URL ------------------------------------------------------------------


def test_authorize_url_carries_state_and_no_scope() -> None:
    # `state` IS supported and echoed back verbatim (confirmed). There is no scope param:
    # Clover permissions live on the app, not the grant.
    url = _client(_capture()[0]).authorize_url(state="signed-state-token")
    parsed = urlparse(url)
    assert parsed.path == "/oauth/v2/authorize"
    params = parse_qs(parsed.query)
    assert params["client_id"] == ["T4RKJYVE63ARA"]
    assert params["state"] == ["signed-state-token"]
    assert params["redirect_uri"] == [_REDIRECT]
    assert "scope" not in params


def test_authorize_url_accepts_a_sub_path_redirect() -> None:
    # Confirmed against the sandbox: a sub-path on the same base domain is accepted.
    url = _client(_capture()[0]).authorize_url(state="s")
    assert parse_qs(urlparse(url).query)["redirect_uri"] == [_REDIRECT]


def test_environment_is_derived_from_the_host() -> None:
    assert environment_for("https://sandbox.dev.clover.com") == "sandbox"
    assert environment_for("https://api.clover.com") == "production"
    assert _client(_capture()[0]).environment == "sandbox"


# -- exchange -----------------------------------------------------------------------


def test_exchange_posts_json_not_form() -> None:
    # THE documented-but-wrong behaviour: Clover's token endpoints 415 on form-encoded.
    # Asserting the content-type here is what stops someone "fixing" this to data=.
    transport, seen = _capture()
    _client(transport).exchange_code("code-1", merchant_id=_MERCHANT, employee_id="EMP1")
    assert seen[0].headers["content-type"] == "application/json"
    assert json.loads(seen[0].content) == {
        "client_id": "T4RKJYVE63ARA",
        "client_secret": "app-secret",
        "code": "code-1",
    }


def test_exchange_hits_the_token_path_and_maps_the_record() -> None:
    transport, seen = _capture()
    record = _client(transport).exchange_code("c", merchant_id=_MERCHANT, employee_id="EMP1")
    assert seen[0].url.path == "/oauth/v2/token"
    assert record.access_token == "eyJhbGciOi.access.jwt"
    assert record.access_token_expiration == 1_785_000_000
    assert record.refresh_token_expiration == 1_816_000_000
    # Identity comes from the CALLBACK, not the token response.
    assert record.merchant_id == _MERCHANT
    assert record.employee_id == "EMP1"
    assert record.environment == "sandbox"
    assert record.obtained_at == int(_FIXED_NOW.timestamp())
    # Nothing has been rotated out yet, so there is no recovery credential.
    assert record.previous_refresh_token is None


def test_a_secret_with_json_hostile_characters_survives_serialisation() -> None:
    # D7: the secret is serialised, never interpolated. A quote/backslash would break a
    # hand-built body and silently corrupt the credential.
    nasty = 'se"cret\\with\nnewline'
    transport, seen = _capture()
    _client(transport, secret=nasty).exchange_code("c", merchant_id=_MERCHANT, employee_id=None)
    assert json.loads(seen[0].content)["client_secret"] == nasty


def test_exchange_rejection_is_typed_invalid_code() -> None:
    transport, _ = _capture(status=400, body={"message": "invalid code"})
    with pytest.raises(CloverOAuthExchangeError) as exc:
        _client(transport).exchange_code("spent", merchant_id=_MERCHANT, employee_id=None)
    assert "invalid code" in (exc.value.detail or "")


# -- refresh ------------------------------------------------------------------------


def test_refresh_sends_no_client_secret() -> None:
    # Confirmed: the refresh leg takes client_id + refresh_token ONLY.
    transport, seen = _capture()
    _client(transport).refresh("clvroar-old", merchant_id=_MERCHANT, employee_id="EMP1")
    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/oauth/v2/refresh"
    assert body == {"client_id": "T4RKJYVE63ARA", "refresh_token": "clvroar-old"}
    assert "client_secret" not in body


def test_refresh_returns_a_new_pair_and_carries_identity_forward() -> None:
    transport, _ = _capture()
    record = _client(transport).refresh("clvroar-old", merchant_id=_MERCHANT, employee_id="EMP1")
    assert record.refresh_token == "clvroar-new"  # single-use: a NEW refresh token
    assert record.merchant_id == _MERCHANT  # not present in the response; carried forward
    assert record.previous_refresh_token is None  # the STORE stamps what it spent, not the client


def test_refresh_401_is_typed_and_carries_the_recovery_header() -> None:
    transport, _ = _capture(
        status=401, body={"message": "token spent"}, headers={RECOVERY_AVAILABLE_HEADER: "true"}
    )
    with pytest.raises(CloverOAuthRefreshRejectedError) as exc:
        _client(transport).refresh("clvroar-old", merchant_id=_MERCHANT, employee_id=None)
    # Advisory only, but it is the datum that explains a lost merchant months later.
    assert f"{RECOVERY_AVAILABLE_HEADER}=true" in (exc.value.detail or "")


# -- recovery -----------------------------------------------------------------------


def test_recovery_posts_the_secret_and_the_recovery_token() -> None:
    transport, seen = _capture()
    _client(transport).recover("clvroar-previous", merchant_id=_MERCHANT, employee_id=None)
    assert seen[0].url.path == "/oauth/v2/recovery"
    assert json.loads(seen[0].content) == {
        "client_id": "T4RKJYVE63ARA",
        "client_secret": "app-secret",
        "recovery_token": "clvroar-previous",
    }


def test_recovery_rejection_is_the_terminal_error() -> None:
    transport, _ = _capture(status=401, body={"message": "outside window"})
    with pytest.raises(CloverOAuthRecoveryExhaustedError):
        _client(transport).recover("clvroar-old", merchant_id=_MERCHANT, employee_id=None)


# -- transient / contract -----------------------------------------------------------


def test_5xx_is_transient_on_every_leg() -> None:
    calls: list[Callable[[CloverOAuthClient], object]] = [
        lambda c: c.exchange_code("x", merchant_id=_MERCHANT, employee_id=None),
        lambda c: c.refresh("x", merchant_id=_MERCHANT, employee_id=None),
        lambda c: c.recover("x", merchant_id=_MERCHANT, employee_id=None),
    ]
    for call in calls:
        transport, _ = _capture(status=503, body={"message": "unavailable"})
        with pytest.raises(CloverOAuthTransientError):
            call(_client(transport))


def test_network_failure_is_transient() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(CloverOAuthTransientError):
        _client(httpx.MockTransport(boom)).refresh("x", merchant_id=_MERCHANT, employee_id=None)


def test_a_missing_expiration_is_a_contract_break_not_a_zero_default() -> None:
    # Defaulting to 0 would make every record look permanently expired and rotate forever.
    transport, _ = _capture(body={"access_token": "a", "refresh_token": "r"})
    with pytest.raises(CloverOAuthError):
        _client(transport).exchange_code("c", merchant_id=_MERCHANT, employee_id=None)


def test_errors_never_carry_the_request_body() -> None:
    # detail is a RESPONSE excerpt only; the exchange/recovery legs put the app secret in
    # the request, and it must never reach an error, a log, or an audit row.
    transport, _ = _capture(status=400, body={"message": "nope"})
    with pytest.raises(CloverOAuthExchangeError) as exc:
        _client(transport, secret="TOPSECRET").exchange_code("c", merchant_id=_MERCHANT, employee_id=None)
    assert "TOPSECRET" not in (exc.value.detail or "")
    assert "TOPSECRET" not in str(exc.value)
