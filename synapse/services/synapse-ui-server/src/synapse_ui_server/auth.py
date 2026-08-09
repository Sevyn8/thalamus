"""Who is calling. ONE discriminator: ``user_type``. There is no second gate and there will not be.

THE LEDGER ITEM THIS SERVICE REFUSES TO INHERIT. ``dis-ui-server`` requires BOTH
``user_type == PLATFORM`` AND a ``dis:ops`` role, described there as defence in depth. This
project's ledger records what it actually bought: two answers to one question, agreeing today and
diverging under impersonation — a PLATFORM user acting for a tenant is one thing by
``user_type`` and another by role, and nothing says which wins.

The fix is one answer, and one answer only holds if nobody adds a second later. So it is stated
rather than merely done: **no role claim will be introduced as a second gate on these routes.**
If a finer distinction is ever needed — an operator who may read the fleet but not one tenant's
runs — it REPLACES ``user_type`` with something that answers the whole question, it does not
join it.

``tenant_id`` COMES FROM THE VERIFIED TOKEN ONLY, never a path parameter, a query string or a
body. It is still unused, because every route here serves PLATFORM callers, for whom Customer
Master omits the claim entirely. The rule is enforced by ``Identity`` carrying it and nothing
else reading it, so a tenant-scoped route starts from the right shape rather than adding one
under pressure.

WHAT ``Identity`` DELIBERATELY DOES NOT CARRY IS THE TOKEN. ``cm_permissions.py`` forwards the
caller's bearer to Customer Master and re-reads it from the request header to do so, rather than
threading it through here. A credential that cannot be reached from the object every handler
holds cannot end up in a log line or a response by accident.

AND THE ONE-DISCRIMINATOR RULE ABOVE IS ABOUT *WHO MAY REACH THESE ROUTES*. Slice 5e added a
permission check on the single route that changes a customer's configuration, delegated to CM's
``/me/can-do``. That is not a second answer to the same question: ``require_platform`` answers
"is this an operator" and the permission answers "may this operator configure a tenant". It
defines nothing locally and duplicates no part of CM's model, which is the property the ledger
item was about. See ``cm_permissions.py``.

WHAT IS NOT COPIED FROM dis-ui-server: its dev-stub HS256 verifier. A second verification path
through the only thing standing between a caller and every tenant's data is a second thing that
can be wrong, and it exists there for historical reasons rather than current ones. Tests here
inject a fake ``Verifier`` at the seam instead, which exercises the real dependency wiring
without adding a second way to accept a token in production.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Protocol

import jwt
from fastapi import Depends, Request
from jwt import PyJWKClient

from synapse_ui_server.config import CLAIM_NAMESPACE

__all__ = [
    "AuthError",
    "Auth0Verifier",
    "Identity",
    "UserType",
    "Verifier",
    "require_platform",
]


class UserType(StrEnum):
    """The claim Customer Master's Auth0 Action stamps. The whole gate."""

    PLATFORM = "PLATFORM"
    TENANT = "TENANT"


@dataclass(frozen=True)
class Identity:
    """A verified caller. Frozen, and built only by a verifier.

    ``tenant_id`` is ``None`` for PLATFORM callers — CM omits the claim entirely rather than
    sending null, which cm-frontend's decoder normalises the same way.
    """

    subject: str
    user_type: UserType
    tenant_id: str | None


class AuthError(Exception):
    """Rejected. Carries a machine-stable ``reason`` and NEVER the token or a claim value.

    Echoing a rejected token into a log is how a credential ends up in Cloud Logging, readable
    by anyone with log access and retained for the bucket's lifetime.
    """

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class Verifier(Protocol):
    """Raw bearer token in, Identity out. The seam tests substitute at."""

    def verify(self, raw: str) -> Identity: ...


def _identity_from_claims(claims: dict[str, Any]) -> Identity:
    """Claims to Identity, refusing anything it cannot read confidently.

    AN UNRECOGNISED ``user_type`` IS REFUSED, not defaulted. Defaulting to TENANT would look
    safe and would silently deny a legitimate operator; defaulting to PLATFORM would hand a
    malformed token the fleet. Neither is a decision this function is entitled to make.
    """
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise AuthError("token carries no subject", reason="invalid")

    raw_type = claims.get(f"{CLAIM_NAMESPACE}user_type")
    if raw_type not in (UserType.PLATFORM.value, UserType.TENANT.value):
        raise AuthError(
            "token carries no recognised user_type claim; Customer Master's Auth0 Action "
            "stamps PLATFORM or TENANT and this service accepts nothing else",
            reason="forbidden",
        )

    raw_tenant = claims.get(f"{CLAIM_NAMESPACE}tenant_id")
    tenant_id = raw_tenant if isinstance(raw_tenant, str) and raw_tenant else None
    return Identity(subject=subject, user_type=UserType(raw_type), tenant_id=tenant_id)


class Auth0Verifier:
    """RS256/JWKS verification of real Auth0 tokens. The only verifier in production.

    One cached ``PyJWKClient`` per process; the first verify performs the JWKS fetch.
    """

    def __init__(self, *, jwks_url: str, issuer: str, audience: str) -> None:
        self._client = PyJWKClient(jwks_url, cache_keys=True)
        self._issuer = issuer
        self._audience = audience

    def verify(self, raw: str) -> Identity:
        try:
            key = self._client.get_signing_key_from_jwt(raw).key
            claims = jwt.decode(
                raw,
                key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                # Explicit rather than inherited: an unverified signature, a missing expiry or a
                # token minted for another API are each a full compromise of this gate.
                options={"require": ["exp", "iat", "aud", "iss", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError(f"token rejected: {type(exc).__name__}", reason="invalid") from exc
        return _identity_from_claims(claims)


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization")
    if not header or not header.lower().startswith("bearer "):
        raise AuthError("no bearer token", reason="missing")
    return header[7:].strip()


async def current_identity(request: Request) -> Identity:
    """The verified caller, or ``AuthError``.

    The verifier is read off ``app.state`` rather than constructed here, so a test injects one
    and production has exactly one.
    """
    verifier: Verifier = request.app.state.verifier
    return verifier.verify(_bearer(request))


async def require_platform(
    identity: Annotated[Identity, Depends(current_identity)],
) -> Identity:
    """Every route in this service. PLATFORM only, on the ``user_type`` claim alone.

    THE ENABLEMENT ROUTE DEPENDS ON THIS ONE RATHER THAN REPLACING IT, so a TENANT token is
    refused here before any outbound call to Customer Master is made and a token that could never
    pass cannot cost a request to another service.

    A TENANT caller reaching a superadmin route is refused here rather than filtered later: the
    fleet read runs under ``rls_platform_session``, which sees every tenant, so there is no
    row-level backstop behind this check. It is the whole boundary.
    """
    if identity.user_type is not UserType.PLATFORM:
        raise AuthError("this endpoint serves PLATFORM callers only", reason="forbidden")
    return identity
