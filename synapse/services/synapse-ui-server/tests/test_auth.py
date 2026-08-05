"""The gate. One discriminator, and every way of getting past it that must not work.

THIS IS THE WHOLE BOUNDARY, which is why it gets this much attention. The fleet read runs under
``rls_platform_session``, which sees every tenant — so there is no row-level backstop behind
``require_platform``. If it admits the wrong caller, that caller sees the entire estate.

NO TEST HERE ASSERTS AGAINST A REIMPLEMENTATION OF THE CLAIM PARSING. The identity is built by
the real ``_identity_from_claims`` from claim dictionaries shaped the way Customer Master's Auth0
Action actually stamps them.
"""

from __future__ import annotations

import pytest
from synapse_ui_server.auth import (
    AuthError,
    Identity,
    UserType,
    _identity_from_claims,
    require_platform,
)
from synapse_ui_server.config import CLAIM_NAMESPACE


def _claims(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "sub": "auth0|operator",
        f"{CLAIM_NAMESPACE}user_type": "PLATFORM",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# The claim shape Customer Master actually produces
# ---------------------------------------------------------------------------


def test_a_platform_token_has_no_tenant() -> None:
    """CM OMITS the claim for PLATFORM users rather than sending null — cm-frontend's decoder
    normalises the same way. Both sides must agree or every operator looks tenant-less."""
    identity = _identity_from_claims(_claims())
    assert identity.user_type is UserType.PLATFORM
    assert identity.tenant_id is None


def test_a_tenant_token_carries_its_tenant() -> None:
    identity = _identity_from_claims(
        _claims(**{f"{CLAIM_NAMESPACE}user_type": "TENANT", f"{CLAIM_NAMESPACE}tenant_id": "t-1"})
    )
    assert identity.user_type is UserType.TENANT
    assert identity.tenant_id == "t-1"


def test_an_unrecognised_user_type_is_refused_not_defaulted() -> None:
    """NEITHER DEFAULT IS SAFE, which is why there is none. Defaulting to TENANT would look
    cautious and silently deny a legitimate operator; defaulting to PLATFORM would hand a
    malformed token the fleet."""
    with pytest.raises(AuthError) as caught:
        _identity_from_claims(_claims(**{f"{CLAIM_NAMESPACE}user_type": "ADMIN"}))
    assert caught.value.reason == "forbidden"


def test_a_missing_user_type_is_refused() -> None:
    with pytest.raises(AuthError, match="recognised user_type"):
        _identity_from_claims({"sub": "auth0|x"})


def test_an_unnamespaced_user_type_is_not_accepted() -> None:
    """A bare ``user_type`` claim is not the one CM stamps. Accepting it would let any issuer
    that happens to use the unqualified name satisfy this gate."""
    with pytest.raises(AuthError):
        _identity_from_claims({"sub": "auth0|x", "user_type": "PLATFORM"})


def test_a_token_without_a_subject_is_refused() -> None:
    with pytest.raises(AuthError, match="no subject"):
        _identity_from_claims({f"{CLAIM_NAMESPACE}user_type": "PLATFORM"})


def test_an_empty_tenant_claim_is_treated_as_absent() -> None:
    """An empty string is not a tenant id. Carrying it through would produce a session scoped to
    '' — which the RLS policies' NULLIF maps to NULL, matching no rows, silently."""
    identity = _identity_from_claims(
        _claims(**{f"{CLAIM_NAMESPACE}user_type": "TENANT", f"{CLAIM_NAMESPACE}tenant_id": ""})
    )
    assert identity.tenant_id is None


# ---------------------------------------------------------------------------
# require_platform
# ---------------------------------------------------------------------------


async def test_a_platform_caller_is_admitted() -> None:
    """The baseline. Without it, every refusal below would also pass against a gate that
    rejected everyone."""
    identity = Identity(subject="s", user_type=UserType.PLATFORM, tenant_id=None)
    assert await require_platform(identity) is identity


async def test_a_tenant_caller_is_refused() -> None:
    """THE ONE THAT MATTERS. There is no row-level backstop behind this: the fleet query runs
    under a PLATFORM session that sees every tenant."""
    with pytest.raises(AuthError) as caught:
        await require_platform(Identity(subject="s", user_type=UserType.TENANT, tenant_id="t-1"))
    assert caught.value.reason == "forbidden"


def test_no_role_claim_is_read_anywhere() -> None:
    """THE LEDGER ITEM, ENFORCED RATHER THAN PROMISED.

    dis-ui-server gates on BOTH ``user_type`` and a ``dis:ops`` role — two answers to one
    question that agree today and diverge under impersonation. The fix is one answer, and one
    answer only holds if nobody adds a second later.

    So this greps the module: no roles claim, no ``dis:ops``, no permissions array. A future
    contributor adding a second gate fails here and has to argue for it.
    """
    from pathlib import Path

    import synapse_ui_server.auth as auth_module

    source = Path(auth_module.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.strip().startswith("#"))
    # The docstring names dis:ops to explain the decision; strip it before checking the code.
    body = code.split('"""', 2)[-1]
    for forbidden in ("dis:ops", "roles", "permissions", "scope"):
        assert forbidden not in body, (
            f"auth.py references {forbidden!r}. This service gates on user_type ALONE; a second "
            "discriminator is the ledger item it exists not to inherit"
        )
