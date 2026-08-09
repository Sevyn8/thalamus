"""The provisioning gate. Delegated to Customer Master, which owns the permission model.

=================================================================================================
WHY THIS IS NOT A SECOND ANSWER TO ``auth.py``'s QUESTION
=================================================================================================
``auth.py`` states, and this module does not weaken, that there will be ONE discriminator for WHO
may reach these routes: the ``user_type`` claim. No role claim joins it, ever. The ledger records
what the alternative bought on dis-ui-server: two answers to one question, agreeing today and
diverging under impersonation.

This asks a DIFFERENT question. ``require_platform`` answers "is this an operator". This answers
"may this operator configure a tenant". Those are not two gates on one question; they are one gate
each on two questions, and the second is only asked by the one route that changes a customer's
configuration. Every read remains PLATFORM-only and nothing else.

AND IT IS NOT A SYNAPSE-LOCAL ROLE CHECK. Nothing here defines a permission, stores a grant, or
restates CM's model. It asks CM the question over HTTP and believes the answer. If CM's cascade
changes, this changes with it because it never had its own copy.

=================================================================================================
THE PERMISSION IS KNOWN-BROADER THAN THE ACT, DELIBERATELY, AND 5e MUST NOT REACH PRODUCTION
=================================================================================================
``ADMIN.TENANTS.CONFIGURE.GLOBAL`` means "Create and configure tenants" (seed row p25). Enabling a
monitor for a tenant IS configuring that tenant, so gating on it is TRUE. It is also BROADER than
the act: anyone who may configure a tenant may now also enable a Synapse analysis for it.

That was accepted knowingly, for three reasons: it is a real CM permission rather than an invented
one, it duplicates no part of CM's model, and it is one line to change here.

THE CORRECT ANSWER IS A ``SYNAPSE`` MODULE AND A ``PROVISION`` RESOURCE IN CM's ENUMS. That is a
Customer Master slice: ``module_code_enum`` holds six values and ``resource_enum`` twelve, both
locked vocabularies in CM's DDL, so a Synapse-specific tuple needs a Postgres enum migration and a
catalogue row there. It cannot be added from this repository.

**HARD CONDITION: 5e must not reach a production tenant until that permission exists.** Staging is
where a known-broader gate is acceptable; a real customer's configuration behind a permission that
means something else is not. This paragraph is the record of that condition, and
``test_provision.py`` asserts the paragraph is still here.

=================================================================================================
FAIL CLOSED. EVERY FAILURE MODE DENIES
=================================================================================================
A timeout, a connection error, a 500, a 502, a 403, a body that is not JSON, a body missing
``allowed``, an ``allowed`` that is not a bool: all deny. Only ``{"allowed": true}`` from a 200
permits.

This is stated as a list rather than as "we catch exceptions" because the failure being prevented
is specific: an ``except Exception: return True`` anywhere on this path turns the gate into
decoration, and a CM outage would then be a window in which anybody who can reach the console can
provision. A denial during a CM outage is a visible, temporary, correct refusal.
"""

from __future__ import annotations

from typing import Annotated, Final

import httpx
from fastapi import Depends, Request

from dis_core.logging import get_logger
from synapse_ui_server.auth import AuthError, Identity, require_platform

__all__ = [
    # httpx is exported so tests can patch THIS module's client rather than the library's.
    # Patching at the call site is what proves the gate uses what the test replaced; mypy
    # rightly refuses to treat an implicit re-export as public API, so it is made explicit.
    "httpx",
    "PROVISION_ACTION",
    "PROVISION_MODULE",
    "PROVISION_RESOURCE",
    "PROVISION_SCOPE",
    "can_configure_tenants",
    "require_tenant_configure",
]

_log = get_logger("synapse-ui-server")

# THE TUPLE, AS FOUR CONSTANTS RATHER THAN A STRING. CM's endpoint takes four query parameters and
# validates each against its own enum, returning 422 on an unknown member. Four constants make a
# typo a 422 from CM naming the bad slot, rather than a silently unmatched dotted string.
#
# See the module docstring before changing any of these: the tuple is known-broader than the act
# and the replacement is a CM enum change, not an edit here.
PROVISION_MODULE: Final[str] = "ADMIN"
PROVISION_RESOURCE: Final[str] = "TENANTS"
PROVISION_ACTION: Final[str] = "CONFIGURE"
PROVISION_SCOPE: Final[str] = "GLOBAL"

# NO ``target_anchor``. It is an ltree path used for the TENANT cascade and is documented as
# ignored on the PLATFORM path, which is the only path a caller here can be on: require_platform
# has already refused a TENANT token before this runs. Sending one would be a parameter CM
# discards, and an ltree that is not a UUID is exactly the confusion cm-frontend's meApi.canDo
# guards against.
_CAN_DO_PATH: Final[str] = "/api/v1/me/can-do"

# A WRITE PATH WAITING ON A SECOND SERVICE NEEDS A CEILING. Cloud Run's own request timeout would
# otherwise be the only bound, and an operator watching a spinner cannot tell a slow gate from a
# hung one. Five seconds is long for a single indexed SELECT behind a warm container and short
# enough that a cold start plus a timeout still returns inside a page load.
_TIMEOUT_SECONDS: Final[float] = 5.0


def _bearer(request: Request) -> str:
    """The caller's raw Auth0 token, re-read from the header.

    FORWARDED, NOT MINTED. The whole point is that CM answers for THIS PERSON, so the credential
    presented to CM has to be the one presented here. Both services verify the same Auth0 access
    token: cm-frontend requests ``audience: https://api.sevyn8.com``, which is what
    SYNAPSE_JWT_AUDIENCE expects and what cm-backend's own verifier requires a ``user_type`` claim
    on. Verified by reading lib/auth0.ts and admin_backend/auth/auth0.py, not assumed.

    Re-read rather than threaded through ``Identity``: that dataclass carries the three claims the
    service uses and deliberately not the token, so a token cannot end up in a log line or a
    response by being somewhere it can be reached.
    """
    header = request.headers.get("authorization")
    if not header or not header.lower().startswith("bearer "):
        # Unreachable behind require_platform, which has already parsed one. Kept because
        # "unreachable" is a claim about today's dependency order.
        raise AuthError("no bearer token", reason="missing")
    return header[7:].strip()


async def can_configure_tenants(*, base_url: str, bearer: str) -> bool:
    """Ask CM whether this caller holds ADMIN.TENANTS.CONFIGURE.GLOBAL. False on ANY doubt.

    Returns a bool rather than raising so the caller decides the status code, and so the two
    reasons for False (denied, and could not ask) are logged here where the detail is, without
    either reaching the operator as a different outcome. They are the same outcome: not permitted.
    """
    url = f"{base_url}{_CAN_DO_PATH}"
    params = {
        "module": PROVISION_MODULE,
        "resource": PROVISION_RESOURCE,
        "action": PROVISION_ACTION,
        "scope": PROVISION_SCOPE,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params, headers={"Authorization": f"Bearer {bearer}"})
    except httpx.HTTPError as exc:
        # Timeout, DNS, connection reset, TLS. All the same answer.
        _log.warning(
            "provisioning gate could not reach Customer Master; denying",
            extra={"severity": "WARNING", "error": type(exc).__name__, "url": url},
        )
        return False

    if response.status_code != 200:
        # 401/403 mean CM rejected the token, 404 means the path is wrong, 5xx means CM is
        # unwell. THE STATUS IS LOGGED AND THE BODY IS NOT: a rejected credential echoed into
        # Cloud Logging is a credential in Cloud Logging for the bucket's lifetime, which is the
        # same rule auth.py's AuthError follows.
        _log.warning(
            "provisioning gate got a non-200 from Customer Master; denying",
            extra={"severity": "WARNING", "status": response.status_code, "url": url},
        )
        return False

    try:
        body = response.json()
    except ValueError:
        _log.warning(
            "provisioning gate got a non-JSON 200 from Customer Master; denying",
            extra={"severity": "WARNING", "url": url},
        )
        return False

    # `is True`, NOT TRUTHINESS. A body of {"allowed": "false"} or {"allowed": 1} would pass a
    # truthy check, and the string "false" is exactly the shape a serialisation bug produces.
    allowed = isinstance(body, dict) and body.get("allowed") is True
    if not allowed:
        _log.info(
            "provisioning gate denied",
            extra={
                "severity": "NOTICE",
                "reason_code": (body.get("reason_code") if isinstance(body, dict) else None),
            },
        )
    return allowed


async def require_tenant_configure(
    request: Request,
    identity: Annotated[Identity, Depends(require_platform)],
) -> Identity:
    """PLATFORM, and permitted to configure tenants. The gate on the one route that provisions.

    DEPENDS ON require_platform RATHER THAN REPLACING IT. A TENANT token is refused before any
    outbound call is made, so a token that could never pass cannot cost a request to CM, and the
    ``user_type`` discriminator stays the single answer to "is this an operator".

    403 WITH THE PERMISSION NAMED. An operator who is refused needs to know which grant to ask
    for, and the tuple is not a secret: it is in CM's own permission matrix screen.
    """
    config = request.app.state.config
    permitted = await can_configure_tenants(base_url=config.cm_api_base_url, bearer=_bearer(request))
    if not permitted:
        raise AuthError(
            "provisioning requires the Customer Master permission "
            f"{PROVISION_MODULE}.{PROVISION_RESOURCE}.{PROVISION_ACTION}.{PROVISION_SCOPE}, "
            "which this account does not hold or which could not be verified. If Customer "
            "Master is unreachable this endpoint denies rather than assumes",
            reason="forbidden",
        )
    return identity
