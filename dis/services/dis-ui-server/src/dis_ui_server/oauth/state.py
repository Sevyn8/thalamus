"""The signed, stateless OAuth ``state`` token (CSRF binding without a session store).

The BFF holds no server-side session (contract 2.1: "no cookies, no CSRF surface"), so the
state is a short-lived HS256 token minted by the authenticated authorize-url endpoint and
verified on complete. The signature binds the tenant + source (an attacker cannot forge a
state naming a victim tenant); the random ``nonce`` makes each state unique; the short
``exp`` bounds replay. The complete endpoint is itself Bearer-authenticated and the
authorization code is single-use at Square, which are the backstops for the replay window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import jwt

from dis_ui_server.oauth.errors import InvalidOauthStateError

_ALGORITHM = "HS256"


@dataclass(frozen=True)
class OAuthStatePayload:
    """The trusted (tenant, source) a verified state authorizes writing tokens for."""

    tenant_id: UUID
    source_id: str


def sign_state(
    *,
    tenant_id: UUID,
    source_id: str,
    key: str,
    nonce: str,
    now: datetime,
    ttl: timedelta,
) -> str:
    """Mint a signed state token binding the tenant + source, expiring at ``now + ttl``."""
    payload = {
        "tid": str(tenant_id),
        "sid": source_id,
        "nonce": nonce,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    return jwt.encode(payload, key, algorithm=_ALGORITHM)


def verify_state(token: str, *, key: str) -> OAuthStatePayload:
    """Validate signature + expiry + shape; return the bound (tenant, source).

    Raises :class:`InvalidOauthStateError` on a bad signature, expiry, or malformed claims.
    """
    try:
        data = jwt.decode(token, key, algorithms=[_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise InvalidOauthStateError("OAuth state is invalid or expired", reason="invalid_state") from exc
    raw_tid = data.get("tid")
    raw_sid = data.get("sid")
    try:
        tenant_id = UUID(str(raw_tid))
    except ValueError as exc:
        raise InvalidOauthStateError("OAuth state tenant is malformed", reason="malformed_state") from exc
    if not isinstance(raw_sid, str) or not raw_sid:
        raise InvalidOauthStateError("OAuth state source is missing", reason="malformed_state")
    return OAuthStatePayload(tenant_id=tenant_id, source_id=raw_sid)
