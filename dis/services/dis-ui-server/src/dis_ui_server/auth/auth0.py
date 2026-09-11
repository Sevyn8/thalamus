"""Auth0Verifier: real Auth0 RS256/JWKS token verifier.

The AUTH0-mode counterpart to the HS256 dev stub in ``verifier.py``. Verifies
real Auth0-issued RS256 tokens by resolving the signing key from Auth0's JWKS by
the token's ``kid``, then validating iss / aud / exp / signature with PyJWT, and
finally the custom claim shape. Produces the SAME :class:`Identity` as the stub's
``verify_token`` (the seam contract), so ``scope.py`` and every handler are
unchanged; the only differences from the stub are the key source (remote JWKS vs
a shared HMAC secret) and the claim location (namespaced vs plain).

Mirrors ``cm-backend/src/admin_backend/auth/auth0.py``: PyJWKClient with
``cache_keys=True`` built ONCE (in this object, constructed in the lifespan), so
a warm-path verify does NO network call; a ``kid`` miss (Auth0 key rotation)
refetches. A JWKS fetch / network failure maps to an ``AuthTokenError``, never a
raw 500. DIS is NOT a per-request introspection gate: it verifies Auth0
tokens locally and resolves tenant/store from the verified claims.

Custom claim namespace is the live Auth0 tenant's (``https://sevyn8.com``),
identical to Customer Master's. iss / aud come from ``JWT_ISSUER`` / ``JWT_AUDIENCE``
(config). Keeps pyjwt[crypto] (already a dep): PyJWKClient ships in PyJWT, so no
new dependency is added.
"""

from __future__ import annotations

from typing import Any

import jwt  # PyJWT
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError

from dis_core.errors import AuthTokenError
from dis_ui_server.auth.identity import Identity, UserType

# Custom claim namespace for the live Auth0 tenant (https://sevyn8.com),
# identical to Customer Master's. Auth0 access tokens can only carry namespaced
# custom claims, so the stub's plain claim names (user_type, tenant_id, ...) are
# read here under this namespace instead. sub is a standard claim (not namespaced).
NAMESPACE = "https://sevyn8.com"
CLAIM_USER_TYPE = f"{NAMESPACE}/user_type"
CLAIM_TENANT_ID = f"{NAMESPACE}/tenant_id"
CLAIM_STORE_ID = f"{NAMESPACE}/store_id"
CLAIM_ROLES = f"{NAMESPACE}/roles"


def _optional_str_claim(claims: dict[str, Any], name: str) -> str | None:
    """A nullable string claim; any other type is a bad-claims failure.

    Mirrors ``verifier.py._optional_str_claim`` (same reject-on-wrong-type shape),
    reading the namespaced claim name.
    """
    value = claims.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise AuthTokenError(f"claim {name!r} is not a string", reason="bad_claims")
    return value


def _roles_claim(claims: dict[str, Any]) -> tuple[str, ...]:
    """``roles: string[]`` (namespaced); absent means no roles.

    Mirrors ``verifier.py._roles_claim``, reading the namespaced claim name.
    """
    value = claims.get(CLAIM_ROLES)
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(r, str) for r in value):
        raise AuthTokenError(f"claim {CLAIM_ROLES!r} is not a list of strings", reason="bad_claims")
    return tuple(value)


def _user_type_claim(claims: dict[str, Any]) -> UserType:
    """The REQUIRED explicit ``user_type`` claim (namespaced).

    Mirrors ``verifier.py._user_type_claim``: absent / empty / unrecognized is a
    hard rejection, never defaulted or downgraded (reject-on-ambiguous).
    """
    value = claims.get(CLAIM_USER_TYPE)
    if not isinstance(value, str) or not value:
        raise AuthTokenError(f"claim {CLAIM_USER_TYPE!r} is missing or empty", reason="bad_claims")
    try:
        return UserType(value)
    except ValueError as exc:
        raise AuthTokenError(
            f"claim {CLAIM_USER_TYPE!r} is not a recognized value", reason="bad_claims"
        ) from exc


class Auth0Verifier:
    """RS256/JWKS verifier for real Auth0 tokens (AUTH0 mode).

    Holds one cached :class:`PyJWKClient` for the process. ``verify`` yields the
    same :class:`Identity` as the stub's ``verify_token``, or raises the same
    ``AuthTokenError`` with a machine-stable ``reason`` (never carrying the token
    or raw claim values).
    """

    def __init__(self, *, jwks_url: str | None, issuer: str | None, audience: str | None) -> None:
        if not jwks_url:
            raise AuthTokenError(
                "Auth0Verifier requires a JWKS URL (AUTH0 mode); config did not derive one",
                reason="invalid",
            )
        if not issuer or not audience:
            raise AuthTokenError(
                "Auth0Verifier requires JWT_ISSUER and JWT_AUDIENCE (AUTH0 mode)",
                reason="invalid",
            )
        self._issuer = issuer
        self._audience = audience
        # One PyJWKClient per process. cache_keys=True so a warm verify reuses the
        # cached signing key and does no network call; a kid miss refetches. No
        # network I/O at construction (fetch is lazy on the first verify).
        self._jwks_client = PyJWKClient(jwks_url, cache_keys=True)

    def verify(self, raw: str) -> Identity:
        """Verify an Auth0 bearer token and yield the :class:`Identity` it asserts.

        Signature, expiry, issuer, audience, and required-claim presence are all
        enforced; any failure is an ``AuthTokenError`` with a coarse ``reason``
        (the response never aids token forgery).
        """
        if not raw:
            raise AuthTokenError("token is empty", reason="invalid")

        # Resolve the signing key from Auth0's JWKS by the token's kid. A kid miss
        # or a fetch / network failure raises PyJWKClientError; a malformed token
        # raises DecodeError. Both collapse to one 401 reason, never a 500.
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(raw)
        except PyJWKClientError as exc:
            raise AuthTokenError("unable to resolve JWKS signing key", reason="invalid") from exc
        except jwt.DecodeError as exc:
            raise AuthTokenError("token malformed", reason="invalid") from exc

        try:
            claims: dict[str, Any] = jwt.decode(
                raw,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthTokenError("token expired", reason="expired") from exc
        except jwt.PyJWTError as exc:
            # Bad signature, wrong issuer/audience, missing required claim,
            # malformed — all collapse to one 401 reason (never aids forgery).
            raise AuthTokenError("token verification failed", reason="invalid") from exc

        sub = claims["sub"]  # presence enforced by options.require above
        if not isinstance(sub, str) or not sub:
            raise AuthTokenError("claim 'sub' is not a non-empty string", reason="bad_claims")

        # user_type is REQUIRED and EXPLICIT; the user_type<->tenant_id
        # coherence is enforced HERE, byte-for-byte as the stub's verify_token does,
        # so no incoherent scope ever reaches a handler. Reject-on-ambiguous.
        user_type = _user_type_claim(claims)
        tenant_id = _optional_str_claim(claims, CLAIM_TENANT_ID)
        if user_type is UserType.TENANT and not tenant_id:
            raise AuthTokenError("TENANT token carries no tenant_id", reason="bad_claims")
        if user_type is UserType.PLATFORM and tenant_id:
            raise AuthTokenError("PLATFORM token must not carry a tenant_id claim", reason="bad_claims")

        return Identity(
            user_id=sub,
            tenant_id=tenant_id,
            store_id=_optional_str_claim(claims, CLAIM_STORE_ID),
            roles=_roles_claim(claims),
            user_type=user_type,
        )
