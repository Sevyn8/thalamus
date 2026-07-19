"""Slice 1 unit tests for Auth0Client (local JWKS verify, D-37).

Parallel to test_stub_auth.py. Mints RS256 tokens with a TEST key carrying the
sevyn8 namespace and the real Auth0 iss / aud, exposes that key via a fake JWKS
resolver, and points Auth0Client's key resolution at it. The real Auth0 tenant
is NEVER hit; all verification is offline.

Groups:
    A1-A3:   happy paths (TENANT, PLATFORM null tenant_id, aud as list)
    B4-B6:   signature / integrity (bad signature, kid mismatch, malformed)
    C7-C11:  claim validation (expired, wrong aud, wrong iss, missing/bad claims)
    D12-D13: AuthContext validation rules (TENANT needs tenant_id) + missing JWT
    E14-E15: settings derivation + namespace constants
    F16:     AuthClient Protocol satisfied by both clients
"""
import time
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.exceptions import PyJWKClientError

from admin_backend.auth.auth0 import (
    CLAIM_EMAIL,
    CLAIM_TENANT_ID,
    CLAIM_USER_ID,
    CLAIM_USER_TYPE,
    NAMESPACE,
    Auth0Client,
)
from admin_backend.auth.protocol import AuthClient
from admin_backend.auth.stub import StubAuthClient
from admin_backend.config import Settings
from admin_backend.errors import (
    AuthInvalidError,
    AuthMissingError,
    InvalidTenantIdError,
)

# The live Auth0 tenant values (used only to shape the fixture tokens; no
# network call is made against them).
_ISS = "https://sevyn8.us.auth0.com/"
_AUD = "https://api.sevyn8.com"
_KID = "test-kid-1"


# ---------------------------------------------------------------------------
# Fixture JWKS: a fake resolver returning a locally-generated test key
# ---------------------------------------------------------------------------


class _FakeSigningKey:
    def __init__(self, key: Any) -> None:
        self.key = key


class _FakeJWKClient:
    """Stands in for PyJWKClient: returns the test public key by kid, offline."""

    def __init__(self, public_key: Any, *, kid: str = _KID) -> None:
        self._public_key = public_key
        self._kid = kid

    def get_signing_key_from_jwt(self, token: str) -> _FakeSigningKey:
        header = jwt.get_unverified_header(token)
        if header.get("kid") != self._kid:
            raise PyJWKClientError(f"no signing key for kid {header.get('kid')!r}")
        return _FakeSigningKey(self._public_key)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )


@pytest.fixture(scope="module")
def other_rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )


@pytest.fixture(scope="module")
def settings() -> Settings:
    """Settings with the real Auth0 iss / aud; database_url / db_schema from .env."""
    return Settings(  # type: ignore[call-arg]
        jwt_issuer=_ISS,
        jwt_audience=_AUD,
    )


@pytest.fixture
def client(settings: Settings, rsa_key: rsa.RSAPrivateKey) -> Auth0Client:
    c = Auth0Client(settings)
    # Point key resolution at the offline test key (no real Auth0 network call).
    c._jwks_client = _FakeJWKClient(rsa_key.public_key())  # type: ignore[assignment]
    return c


def _mint(
    signing_key: rsa.RSAPrivateKey,
    *,
    user_type: str,
    user_id: UUID | None = None,
    tenant_id: UUID | None = None,
    email: str = "alice@tenant-a.test",
    sub: str = "auth0|abc123",
    iss: str = _ISS,
    aud: Any = _AUD,
    exp_offset_seconds: int = 3600,
    kid: str = _KID,
    omit_claims: tuple[str, ...] = (),
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Mint an RS256 token carrying the sevyn8-namespace claims."""
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": sub,
        "iss": iss,
        "aud": aud,
        "iat": now,
        "exp": now + exp_offset_seconds,
        CLAIM_USER_ID: str(user_id if user_id is not None else uuid4()),
        CLAIM_USER_TYPE: user_type,
        CLAIM_EMAIL: email,
    }
    if tenant_id is not None:
        payload[CLAIM_TENANT_ID] = str(tenant_id)
    for k in omit_claims:
        payload.pop(k, None)
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, signing_key, algorithm="RS256", headers={"kid": kid})


# ---------------------------------------------------------------------------
# Group A: happy paths
# ---------------------------------------------------------------------------


def test_a1_tenant_jwt_roundtrip(client: Auth0Client, rsa_key: rsa.RSAPrivateKey) -> None:
    tenant_a = uuid4()
    user_a = uuid4()
    token = _mint(
        rsa_key, user_type="TENANT", user_id=user_a, tenant_id=tenant_a,
        email="alice@tenant-a.test",
    )
    ctx = client.verify(token)
    assert ctx.user_type == "TENANT"
    assert ctx.tenant_id == tenant_a
    assert ctx.user_id == user_a
    assert ctx.email == "alice@tenant-a.test"
    assert ctx.iss == _ISS
    assert ctx.aud == _AUD


def test_a2_platform_jwt_null_tenant(client: Auth0Client, rsa_key: rsa.RSAPrivateKey) -> None:
    user_p = uuid4()
    token = _mint(rsa_key, user_type="PLATFORM", user_id=user_p, email="ops@sevyn8.test")
    ctx = client.verify(token)
    assert ctx.user_type == "PLATFORM"
    assert ctx.tenant_id is None
    assert ctx.user_id == user_p


def test_a3_aud_as_list_accepted(client: Auth0Client, rsa_key: rsa.RSAPrivateKey) -> None:
    token = _mint(
        rsa_key, user_type="PLATFORM",
        aud=[_AUD, "https://sevyn8.us.auth0.com/userinfo"],
    )
    ctx = client.verify(token)
    assert isinstance(ctx.aud, list)
    assert _AUD in ctx.aud


# ---------------------------------------------------------------------------
# Group B: signature / integrity
# ---------------------------------------------------------------------------


def test_b4_bad_signature_rejected(
    client: Auth0Client, other_rsa_key: rsa.RSAPrivateKey
) -> None:
    # Signed with a different key than the fake JWKS returns.
    token = _mint(other_rsa_key, user_type="PLATFORM")
    with pytest.raises(AuthInvalidError):
        client.verify(token)


def test_b5_kid_mismatch_rejected(client: Auth0Client, rsa_key: rsa.RSAPrivateKey) -> None:
    token = _mint(rsa_key, user_type="PLATFORM", kid="unknown-kid")
    with pytest.raises(AuthInvalidError):
        client.verify(token)


def test_b6_malformed_token_rejected(client: Auth0Client) -> None:
    with pytest.raises(AuthInvalidError):
        client.verify("not.a.jwt")


# ---------------------------------------------------------------------------
# Group C: claim validation
# ---------------------------------------------------------------------------


def test_c7_expired_rejected(client: Auth0Client, rsa_key: rsa.RSAPrivateKey) -> None:
    token = _mint(rsa_key, user_type="PLATFORM", exp_offset_seconds=-10)
    with pytest.raises(AuthInvalidError):
        client.verify(token)


def test_c8_wrong_audience_rejected(client: Auth0Client, rsa_key: rsa.RSAPrivateKey) -> None:
    token = _mint(rsa_key, user_type="PLATFORM", aud="https://wrong.example")
    with pytest.raises(AuthInvalidError):
        client.verify(token)


def test_c9_wrong_issuer_rejected(client: Auth0Client, rsa_key: rsa.RSAPrivateKey) -> None:
    token = _mint(rsa_key, user_type="PLATFORM", iss="https://evil.example/")
    with pytest.raises(AuthInvalidError):
        client.verify(token)


def test_c10_missing_user_id_rejected(client: Auth0Client, rsa_key: rsa.RSAPrivateKey) -> None:
    token = _mint(rsa_key, user_type="PLATFORM", omit_claims=(CLAIM_USER_ID,))
    with pytest.raises(AuthInvalidError):
        client.verify(token)


def test_c11a_bad_user_type_rejected(client: Auth0Client, rsa_key: rsa.RSAPrivateKey) -> None:
    token = _mint(rsa_key, user_type="PLATFORM", extra_claims={CLAIM_USER_TYPE: "ROOT"})
    with pytest.raises(AuthInvalidError):
        client.verify(token)


def test_c11b_missing_email_rejected(client: Auth0Client, rsa_key: rsa.RSAPrivateKey) -> None:
    token = _mint(rsa_key, user_type="PLATFORM", omit_claims=(CLAIM_EMAIL,))
    with pytest.raises(AuthInvalidError):
        client.verify(token)


def test_c11c_malformed_tenant_id_rejected(
    client: Auth0Client, rsa_key: rsa.RSAPrivateKey
) -> None:
    token = _mint(
        rsa_key, user_type="PLATFORM", extra_claims={CLAIM_TENANT_ID: "not-a-uuid"}
    )
    with pytest.raises(InvalidTenantIdError):
        client.verify(token)


# ---------------------------------------------------------------------------
# Group D: AuthContext validation rules + missing JWT
# ---------------------------------------------------------------------------


def test_d12_tenant_type_without_tenant_id_rejected(
    client: Auth0Client, rsa_key: rsa.RSAPrivateKey
) -> None:
    # TENANT user_type with no tenant_id fails the AuthContext model validator,
    # wrapped as AuthInvalidError.
    token = _mint(rsa_key, user_type="TENANT")  # no tenant_id
    with pytest.raises(AuthInvalidError):
        client.verify(token)


def test_d13_missing_jwt_rejected(client: Auth0Client) -> None:
    with pytest.raises(AuthMissingError):
        client.verify("")
    with pytest.raises(AuthMissingError):
        client.verify(None)


# ---------------------------------------------------------------------------
# Group E: settings derivation + namespace constants
# ---------------------------------------------------------------------------


def test_e14_jwks_url_derived_from_issuer(settings: Settings) -> None:
    assert settings.auth0_jwks_url == f"{_ISS}.well-known/jwks.json"


def test_e15_namespace_constants(settings: Settings) -> None:
    assert NAMESPACE == "https://sevyn8.com"
    assert CLAIM_TENANT_ID == "https://sevyn8.com/tenant_id"
    assert CLAIM_USER_TYPE == "https://sevyn8.com/user_type"
    assert CLAIM_USER_ID == "https://sevyn8.com/user_id"
    assert CLAIM_EMAIL == "https://sevyn8.com/email"


def test_e15b_jwks_url_override_respected() -> None:
    override = Settings(  # type: ignore[call-arg]
        jwt_issuer=_ISS,
        jwt_audience=_AUD,
        auth0_jwks_url="https://custom.sevyn8.example/keys.json",
    )
    assert override.auth0_jwks_url == "https://custom.sevyn8.example/keys.json"


# ---------------------------------------------------------------------------
# Group F: Protocol satisfaction
# ---------------------------------------------------------------------------


def test_f16_both_clients_satisfy_auth_client_protocol(settings: Settings) -> None:
    assert isinstance(Auth0Client(settings), AuthClient)
    assert isinstance(StubAuthClient(settings), AuthClient)
