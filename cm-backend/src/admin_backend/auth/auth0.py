"""Auth0Client: production JWT verifier (local JWKS verify, D-37).

Verifies real Auth0-issued RS256 tokens by resolving the signing key from
Auth0's JWKS by the token's ``kid``, then validating iss / aud / exp /
signature with PyJWT. Produces the SAME AuthContext as StubAuthClient (D-24
identity-only claims), so the middleware and every handler are unchanged; the
only difference from the stub is the key source (remote JWKS vs a local public
key file) and the claim namespace.

Per D-37 CM/admin-backend is NOT a per-request introspection gate: each service
verifies Auth0 tokens locally. PyJWKClient caches signing keys (cache_keys), so
a warm-path verify does NO network call; a ``kid`` miss (Auth0 key rotation)
refetches. A JWKS fetch / network failure is mapped to a typed auth error, never
a raw 500. The client is constructed ONCE (main.py lifespan), not per request.

Custom claim namespace is the live Auth0 tenant's (https://sevyn8.com), distinct
from StubAuthClient's https://ithina.com. iss / aud are read from jwt_issuer /
jwt_audience (reused for AUTH0 mode; no separate auth0_issuer / auth0_audience
settings). Keeps pyjwt[crypto] per D-26: PyJWKClient ships in PyJWT, so no new
dependency is added.
"""
from uuid import UUID

import jwt  # PyJWT
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError

from admin_backend.auth.context import AuthContext
from admin_backend.config import Settings
from admin_backend.errors import (
    AuthInvalidError,
    AuthMissingError,
    InvalidTenantIdError,
)


# Custom claim namespace for the live Auth0 tenant (https://sevyn8.com).
# Deliberately distinct from StubAuthClient's https://ithina.com; the stub
# path and its tests are untouched.
NAMESPACE = "https://sevyn8.com"
CLAIM_TENANT_ID = f"{NAMESPACE}/tenant_id"
CLAIM_USER_TYPE = f"{NAMESPACE}/user_type"
CLAIM_USER_ID = f"{NAMESPACE}/user_id"
CLAIM_EMAIL = f"{NAMESPACE}/email"


class Auth0Client:
    """JWT verification client for real Auth0 tokens (local JWKS verify).

    Resolves the RS256 signing key from Auth0's JWKS by ``kid`` and validates
    issuer, audience, expiry, and signature, then the custom claim shape per
    D-24. Returns an AuthContext identical in shape to StubAuthClient's, or
    raises the same typed error.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        jwks_url = settings.auth0_jwks_url
        if jwks_url is None:  # pragma: no cover - validator always derives it
            raise RuntimeError(
                "auth0_jwks_url is not configured; expected it to be derived "
                "from jwt_issuer by Settings.derive_auth0_jwks_url"
            )
        # One PyJWKClient per process (built here, in the lifespan-constructed
        # client). cache_keys=True so a warm verify reuses the cached signing
        # key and does no network call (D-37); a kid miss refetches.
        self._jwks_client = PyJWKClient(jwks_url, cache_keys=True)

    def verify(self, jwt_string: str | None) -> AuthContext:
        """Verify an Auth0 JWT and return a validated AuthContext.

        Raises:
            AuthMissingError: jwt_string is empty or None.
            AuthInvalidError: JWKS resolution, signature, expiry, audience,
                issuer, or claim shape failed.
            InvalidTenantIdError: tenant_id claim is present but is not a
                valid UUID.
        """
        if not jwt_string:
            raise AuthMissingError("JWT string is empty or None")

        # Resolve the signing key from Auth0's JWKS by the token's kid. A kid
        # miss or a fetch / network failure raises PyJWKClientError; a malformed
        # token raises DecodeError. Both become AuthInvalidError, never a 500.
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(jwt_string)
        except PyJWKClientError as e:
            raise AuthInvalidError(f"Unable to resolve JWKS signing key: {e}") from e
        except jwt.DecodeError as e:
            raise AuthInvalidError(f"Token malformed: {e}") from e

        try:
            payload = jwt.decode(
                jwt_string,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._settings.jwt_audience,
                issuer=self._settings.jwt_issuer,
            )
        except jwt.ExpiredSignatureError as e:
            raise AuthInvalidError(f"Token expired: {e}") from e
        except jwt.InvalidAudienceError as e:
            raise AuthInvalidError(f"Token audience mismatch: {e}") from e
        except jwt.InvalidIssuerError as e:
            raise AuthInvalidError(f"Token issuer mismatch: {e}") from e
        except jwt.InvalidSignatureError as e:
            raise AuthInvalidError(f"Token signature invalid: {e}") from e
        except jwt.DecodeError as e:
            raise AuthInvalidError(f"Token malformed: {e}") from e

        # Extract and validate custom claims (same shape as StubAuthClient).
        tenant_id_raw = payload.get(CLAIM_TENANT_ID)
        tenant_id: UUID | None
        if tenant_id_raw is None:
            tenant_id = None
        else:
            try:
                tenant_id = UUID(tenant_id_raw)
            except (ValueError, TypeError, AttributeError) as e:
                raise InvalidTenantIdError(
                    f"tenant_id claim is not a valid UUID: {tenant_id_raw!r}"
                ) from e

        user_id_raw = payload.get(CLAIM_USER_ID)
        if not user_id_raw:
            raise AuthInvalidError(f"Missing required claim: {CLAIM_USER_ID}")
        try:
            user_id = UUID(user_id_raw)
        except (ValueError, TypeError, AttributeError) as e:
            raise AuthInvalidError(
                f"user_id claim is not a valid UUID: {user_id_raw!r}"
            ) from e

        user_type = payload.get(CLAIM_USER_TYPE)
        if user_type not in ("PLATFORM", "TENANT"):
            raise AuthInvalidError(
                f"user_type claim must be 'PLATFORM' or 'TENANT'; got: {user_type!r}"
            )

        email = payload.get(CLAIM_EMAIL)
        if not email:
            raise AuthInvalidError(f"Missing required claim: {CLAIM_EMAIL}")

        # Construct AuthContext (its validators run here).
        try:
            return AuthContext(
                sub=payload["sub"],
                iss=payload["iss"],
                aud=payload["aud"],
                exp=payload["exp"],
                user_id=user_id,
                tenant_id=tenant_id,
                user_type=user_type,
                email=email,
            )
        except Exception as e:
            raise AuthInvalidError(
                f"Token claims failed AuthContext validation: {e}"
            ) from e
