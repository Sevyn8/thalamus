"""AuthClient: the structural contract every auth verifier satisfies.

Both StubAuthClient (build / dev / test default) and Auth0Client (production,
local JWKS verify per D-37) implement this Protocol. main.py picks one by
AUTH_CLIENT_MODE and stores it on app.state.auth_client; the auth middleware
depends only on this Protocol, so the STUB-vs-AUTH0 substitution is covered by
mypy --strict at the seam rather than pinned to a concrete class.

runtime_checkable so tests can assert both clients satisfy it. Note: a
runtime isinstance check only verifies the method is present, not its
signature; mypy --strict is what verifies the full contract statically.
"""
from typing import Protocol, runtime_checkable

from admin_backend.auth.context import AuthContext


@runtime_checkable
class AuthClient(Protocol):
    """Verifies a bearer JWT and returns the identity context (D-24).

    Contract (identical for every implementation):
      - jwt_string None or empty -> AuthMissingError
      - signature / iss / aud / exp / claim-shape failure -> AuthInvalidError
      - tenant_id claim present but not a UUID -> InvalidTenantIdError
      - success -> a validated AuthContext (identity claims only, no roles /
        permissions, per D-24)
    """

    def verify(self, jwt_string: str | None) -> AuthContext:
        ...
