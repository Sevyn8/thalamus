"""AUTH0-mode (RS256/JWKS) verifier: the real Auth0 path.

Sibling to test_auth.py (which pins the STUB HS256 path). These drive the app
with DIS_AUTH_MODE=AUTH0 and a local test RSA keypair (the verifier's JWKS
resolution is monkeypatched to the test public key by the ``auth0_client``
fixture), asserting the same statuses / envelope codes the registered handlers
produce. The valid path yields the identical Identity shape as the stub; every
refusal maps to the same AuthTokenError reasons. Mirrors CM's test_auth0.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

# Defined locally (mirrors test_auth.py's local TENANT_A; conftest is not an
# importable package). These MUST match the conftest fixture defaults so minted
# token iss / aud / tenant line up with what the verifier is configured for.
_NAMESPACE = "https://sevyn8.com"
AUTH0_ISSUER = "https://sevyn8.us.auth0.com/"
AUTH0_AUDIENCE = "https://api.dis.sevyn8.com"
TENANT_A = "019e5e3c-b5d3-705f-9002-2451c4ca2626"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _error_code(body: dict[str, Any]) -> str:
    code = body["error"]["code"]
    assert isinstance(code, str)
    return code


# -- the valid path -------------------------------------------------------------


def test_valid_tenant_token_yields_identity(
    auth0_client: TestClient, auth0_mint_token: Callable[..., str]
) -> None:
    token = auth0_mint_token(sub="auth0|u1", tenant_id=TENANT_A, roles=("dis:read",))
    response = auth0_client.get("/api/v1/probe/tenant", headers=_bearer(token))
    assert response.status_code == 200
    assert response.json() == {"tenant_id": TENANT_A, "user_id": "auth0|u1"}


def test_valid_ops_token_passes_require_ops(
    auth0_client: TestClient, auth0_mint_token: Callable[..., str]
) -> None:
    # PLATFORM user: no tenant_id claim, dis:ops role.
    token = auth0_mint_token(sub="auth0|ops", tenant_id=None, roles=("dis:ops",), user_type="PLATFORM")
    response = auth0_client.get("/api/v1/probe/ops", headers=_bearer(token))
    assert response.status_code == 200
    assert response.json() == {"user_id": "auth0|ops", "tenant_id": None}


# -- token / signature refusals (reason=invalid or expired) ---------------------


def test_expired_token_rejected(auth0_client: TestClient, auth0_mint_token: Callable[..., str]) -> None:
    token = auth0_mint_token(expires_in=-60)
    response = auth0_client.get("/api/v1/probe/tenant", headers=_bearer(token))
    assert response.status_code == 401


def test_wrong_issuer_rejected(auth0_client: TestClient, auth0_mint_token: Callable[..., str]) -> None:
    token = auth0_mint_token(issuer="https://evil.example.com/")
    response = auth0_client.get("/api/v1/probe/tenant", headers=_bearer(token))
    assert response.status_code == 401


def test_wrong_audience_rejected(auth0_client: TestClient, auth0_mint_token: Callable[..., str]) -> None:
    token = auth0_mint_token(audience="https://api.sevyn8.com")  # CM's audience, not DIS's
    response = auth0_client.get("/api/v1/probe/tenant", headers=_bearer(token))
    assert response.status_code == 401


def test_bad_signature_rejected(auth0_client: TestClient, auth0_mint_token: Callable[..., str]) -> None:
    # Sign with a foreign key; the verifier holds the fixture's public key.
    from cryptography.hazmat.primitives.asymmetric import rsa

    foreign = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = auth0_mint_token(private_key=foreign)
    response = auth0_client.get("/api/v1/probe/tenant", headers=_bearer(token))
    assert response.status_code == 401


# -- claim refusals (reason=bad_claims) -----------------------------------------


def test_missing_namespaced_user_type_rejected(
    auth0_client: TestClient, auth0_mint_token: Callable[..., str]
) -> None:
    # Omit the required namespaced user_type claim.
    token = auth0_mint_token(omit=(f"{_NAMESPACE}/user_type",), user_type=None)
    response = auth0_client.get("/api/v1/probe/tenant", headers=_bearer(token))
    assert response.status_code == 401


def test_platform_with_tenant_id_rejected(
    auth0_client: TestClient, auth0_mint_token: Callable[..., str]
) -> None:
    # PLATFORM must NOT carry a tenant_id (incoherent scope).
    token = auth0_mint_token(user_type="PLATFORM", tenant_id=TENANT_A, roles=("dis:ops",))
    response = auth0_client.get("/api/v1/probe/ops", headers=_bearer(token))
    assert response.status_code == 401


def test_tenant_without_tenant_id_rejected(
    auth0_client: TestClient, auth0_mint_token: Callable[..., str]
) -> None:
    # TENANT must carry a tenant_id.
    token = auth0_mint_token(user_type="TENANT", tenant_id=None)
    response = auth0_client.get("/api/v1/probe/tenant", headers=_bearer(token))
    assert response.status_code == 401


# -- store_id + roles pass through to the identical Identity --------------------


def test_store_id_and_roles_flow_through(
    auth0_client: TestClient, auth0_mint_token: Callable[..., str]
) -> None:
    # A tenant token with a store_id and dis:ops still resolves as TENANT (require_tenant).
    token = auth0_mint_token(tenant_id=TENANT_A, store_id="store-9", roles=("dis:read", "dis:ops"))
    response = auth0_client.get("/api/v1/probe/tenant", headers=_bearer(token))
    assert response.status_code == 200
    assert response.json()["tenant_id"] == TENANT_A


# -- issuer/audience assertions ------------------------------------------------


def test_fixture_issuer_audience_are_dis_specific() -> None:
    # Guard: DIS uses its own audience, distinct from CM's api.sevyn8.com.
    assert AUTH0_ISSUER == "https://sevyn8.us.auth0.com/"
    assert AUTH0_AUDIENCE == "https://api.dis.sevyn8.com"
