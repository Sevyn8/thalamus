"""P1-SEC-001: when may this service run the HS256 dev-stub verifier?

THE THREAT THIS PINS. ``DEV_STUB_SECRET`` is a constant in verifier.py and, until
P1-SEC-001, also shipped in the public dis-ui-ver2 JavaScript bundle. Treat it as permanently
published: anybody can sign a token with it, choose their own ``tenant_id`` claim, and that
claim becomes the RLS GUC. The only thing standing between that and real rows is whether a
process will select ``StubVerifier`` at all.

TWO INDEPENDENT CONDITIONS, BOTH REQUIRED:

  1. ``DIS_ALLOW_STUB_AUTH`` explicitly declares the process local/test, and
  2. ``POSTGRES_URL`` points at loopback.

The second was here first and is not sufficient on its own, which is the whole reason for the
first. A Cloud SQL Auth Proxy sidecar listens on 127.0.0.1 *inside a deployed container*, so a
loopback database is entirely compatible with running in staging against production data.
Database topology describes the connection; it is not a statement about where the application
is. Locality has to be declared by whoever starts the process.

Both directions are tested. A file that only proved refusals would pass just as happily
against a service that refused STUB unconditionally — including one that had lost the ability
to run local fixtures at all — so the sanctioned local posture is asserted to SUCCEED.
"""

from __future__ import annotations

import pytest

from dis_core.errors import DisError
from dis_ui_server.config import UiServerConfig

_LOOPBACK_URL = "postgresql+psycopg://u:p@127.0.0.1:5433/ithina_dis_db"
_LOCALHOST_URL = "postgresql+psycopg://u:p@localhost:5433/ithina_dis_db"
# A private IP is what staging actually uses; the Cloud SQL socket form parses to no host.
_REMOTE_URL = "postgresql+psycopg://u:p@10.24.0.3:5432/thalamus"
_SOCKET_URL = "postgresql+psycopg:///thalamus?host=/cloudsql/proj:region:inst"

_AUTH0_ISSUER = "https://sevyn8.us.auth0.com/"
_AUTH0_AUDIENCE = "https://api.dis.sevyn8.com"


def _base_env(monkeypatch: pytest.MonkeyPatch, *, postgres_url: str) -> None:
    """Everything required regardless of auth mode, and nothing auth-related."""
    monkeypatch.setenv("POSTGRES_URL", postgres_url)
    monkeypatch.setenv("GCS_BUCKET_BRONZE", "ithina-bronze-raw")
    monkeypatch.setenv("PUBSUB_PROJECT_ID", "local-dis")
    for name in ("DIS_AUTH_MODE", "DIS_ALLOW_STUB_AUTH", "JWT_ISSUER", "JWT_AUDIENCE"):
        monkeypatch.delenv(name, raising=False)


# --- AUTH0: unchanged behaviour, both postures ------------------------------------------------


@pytest.mark.parametrize(
    ("label", "postgres_url"),
    [
        ("deployed/private-ip", _REMOTE_URL),
        ("deployed/cloudsql-socket", _SOCKET_URL),
        ("local", _LOOPBACK_URL),
    ],
)
def test_auth0_is_allowed_in_every_posture(
    label: str, postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AUTH0 is the real verifier and this tranche must not narrow it."""
    _base_env(monkeypatch, postgres_url=postgres_url)
    monkeypatch.setenv("DIS_AUTH_MODE", "AUTH0")
    monkeypatch.setenv("JWT_ISSUER", _AUTH0_ISSUER)
    monkeypatch.setenv("JWT_AUDIENCE", _AUTH0_AUDIENCE)

    config = UiServerConfig.from_env()

    assert config.auth_mode == "AUTH0", label


def test_auth0_ignores_the_stub_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    """The opt-in gates STUB only; it must not become a second way to alter AUTH0."""
    _base_env(monkeypatch, postgres_url=_REMOTE_URL)
    monkeypatch.setenv("DIS_AUTH_MODE", "AUTH0")
    monkeypatch.setenv("DIS_ALLOW_STUB_AUTH", "1")
    monkeypatch.setenv("JWT_ISSUER", _AUTH0_ISSUER)
    monkeypatch.setenv("JWT_AUDIENCE", _AUTH0_AUDIENCE)

    assert UiServerConfig.from_env().auth_mode == "AUTH0"


# --- STUB: allowed only in the sanctioned local posture ---------------------------------------


@pytest.mark.parametrize("postgres_url", [_LOOPBACK_URL, _LOCALHOST_URL])
@pytest.mark.parametrize("permission", ["1", "true", "TRUE", "yes", " 1 "])
def test_stub_is_allowed_with_explicit_permission_and_a_loopback_database(
    postgres_url: str, permission: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE SUCCESS PATH. Without this, every refusal below would also pass against a build
    that had simply removed local fixture auth, and developers would lose the workflow."""
    _base_env(monkeypatch, postgres_url=postgres_url)
    monkeypatch.setenv("DIS_AUTH_MODE", "STUB")
    monkeypatch.setenv("DIS_ALLOW_STUB_AUTH", permission)

    assert UiServerConfig.from_env().auth_mode == "STUB"


def test_stub_is_refused_without_the_explicit_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    """A loopback database alone is NOT a declaration of locality — the Cloud SQL Auth Proxy
    case. This is the condition P1-SEC-001 added."""
    _base_env(monkeypatch, postgres_url=_LOOPBACK_URL)
    monkeypatch.setenv("DIS_AUTH_MODE", "STUB")

    with pytest.raises(DisError, match="DIS_ALLOW_STUB_AUTH"):
        UiServerConfig.from_env()


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe", "2"])
def test_stub_is_refused_for_any_non_affirmative_permission(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Present-but-not-yes is a no. A variable set to "0" reads as configured at a glance."""
    _base_env(monkeypatch, postgres_url=_LOOPBACK_URL)
    monkeypatch.setenv("DIS_AUTH_MODE", "STUB")
    monkeypatch.setenv("DIS_ALLOW_STUB_AUTH", value)

    with pytest.raises(DisError, match="DIS_ALLOW_STUB_AUTH"):
        UiServerConfig.from_env()


@pytest.mark.parametrize(
    ("label", "postgres_url"),
    [("staging private IP", _REMOTE_URL), ("cloud sql socket", _SOCKET_URL)],
)
def test_stub_is_refused_against_a_remote_database_even_with_permission(
    label: str, postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pre-existing guard, unweakened. Both conditions are required, not either."""
    _base_env(monkeypatch, postgres_url=postgres_url)
    monkeypatch.setenv("DIS_AUTH_MODE", "STUB")
    monkeypatch.setenv("DIS_ALLOW_STUB_AUTH", "1")

    with pytest.raises(DisError, match="POSTGRES_URL"):
        UiServerConfig.from_env()


def test_stub_is_refused_when_the_database_url_cannot_be_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A guard that cannot read its input has checked nothing."""
    _base_env(monkeypatch, postgres_url="not a url at all::::")
    monkeypatch.setenv("DIS_AUTH_MODE", "STUB")
    monkeypatch.setenv("DIS_ALLOW_STUB_AUTH", "1")

    with pytest.raises(DisError):
        UiServerConfig.from_env()


def test_a_deployed_posture_cannot_reach_stub_by_any_combination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The finding restated as one assertion: a deployment that sets STUB crashloops.

    Staging's actual shape — no stub permission anywhere in its Terraform, a managed database —
    fails on the first condition, and would fail on the second too.
    """
    _base_env(monkeypatch, postgres_url=_SOCKET_URL)
    monkeypatch.setenv("DIS_AUTH_MODE", "STUB")

    with pytest.raises(DisError):
        UiServerConfig.from_env()


# --- Mode resolution itself -------------------------------------------------------------------


def test_missing_mode_still_defaults_to_auth0(monkeypatch: pytest.MonkeyPatch) -> None:
    """The safe default, re-asserted here because this file owns the auth-selection policy.

    An absent variable selects the RS256/JWKS verifier and then refuses to start without an
    issuer and audience, so a dropped variable crashloops rather than silently accepting
    forged tokens.
    """
    _base_env(monkeypatch, postgres_url=_REMOTE_URL)
    monkeypatch.setenv("JWT_ISSUER", _AUTH0_ISSUER)
    monkeypatch.setenv("JWT_AUDIENCE", _AUTH0_AUDIENCE)

    assert UiServerConfig.from_env().auth_mode == "AUTH0"


def test_missing_mode_with_stub_permission_still_defaults_to_auth0(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The opt-in permits STUB; it never SELECTS it. Selection stays with DIS_AUTH_MODE."""
    _base_env(monkeypatch, postgres_url=_LOOPBACK_URL)
    monkeypatch.setenv("DIS_ALLOW_STUB_AUTH", "1")
    monkeypatch.setenv("JWT_ISSUER", _AUTH0_ISSUER)
    monkeypatch.setenv("JWT_AUDIENCE", _AUTH0_AUDIENCE)

    assert UiServerConfig.from_env().auth_mode == "AUTH0"


@pytest.mark.parametrize("mode", ["stub", "Stub", "NONE", "auth0", "OFF", "DISABLED"])
def test_an_unrecognised_mode_is_refused(mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Including lowercase 'stub' and 'auth0': the comparison is exact, so a near-miss is a
    crashloop rather than a silent fall-through to whichever branch happens to catch it."""
    _base_env(monkeypatch, postgres_url=_LOOPBACK_URL)
    monkeypatch.setenv("DIS_AUTH_MODE", mode)
    monkeypatch.setenv("DIS_ALLOW_STUB_AUTH", "1")

    with pytest.raises(DisError, match="not a recognized mode"):
        UiServerConfig.from_env()
