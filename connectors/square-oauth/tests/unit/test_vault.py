"""Vault logic against an in-memory backend, plus the Google adapter against a fake client.

No network: the meat (naming + payload + read/write contract) is tested through the
SecretBackend Protocol; the Google adapter is tested through a fake SecretManager client.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from google.api_core.exceptions import NotFound

from thalamus_square_oauth.payload import SquareTokenSet
from thalamus_square_oauth.vault import GoogleSecretBackend, SquareTokenVault

# NotFound.__init__ is untyped (google-api-core ships py.typed but no annotations there);
# call it through an Any alias so mypy --strict does not flag a no-untyped-call in tests.
_NotFound: Any = NotFound

_TENANT = UUID("019e5e3c-b5d3-705f-9002-2451c4ca2626")
_SOURCE = "square-prod"


def _token_set(access: str = "atok") -> SquareTokenSet:
    return SquareTokenSet(
        access_token=access,
        refresh_token="rtok",
        expires_at="2026-08-01T00:00:00Z",
        merchant_id="M1",
        token_type="bearer",
        scopes=("ITEMS_READ",),
        obtained_at="2026-07-01T00:00:00Z",
        environment="sandbox",
    )


class _FakeBackend:
    """In-memory SecretBackend: one latest-bytes value per secret id."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def access_latest(self, secret_id: str) -> bytes | None:
        return self.store.get(secret_id)

    def add_version(self, secret_id: str, data: bytes) -> None:
        self.store[secret_id] = data


def test_read_missing_returns_none() -> None:
    vault = SquareTokenVault(_FakeBackend())
    assert vault.read(_TENANT, _SOURCE) is None


def test_write_then_read_round_trips() -> None:
    vault = SquareTokenVault(_FakeBackend())
    token_set = _token_set()
    vault.write(_TENANT, _SOURCE, token_set)
    assert vault.read(_TENANT, _SOURCE) == token_set


def test_write_twice_latest_wins() -> None:
    vault = SquareTokenVault(_FakeBackend())
    vault.write(_TENANT, _SOURCE, _token_set("first"))
    vault.write(_TENANT, _SOURCE, _token_set("second"))
    read = vault.read(_TENANT, _SOURCE)
    assert read is not None
    assert read.access_token == "second"


# ----- Google adapter against a fake SecretManagerServiceClient -----


@dataclass
class _FakePayload:
    data: bytes


@dataclass
class _FakeAccessResponse:
    payload: _FakePayload


class _FakeSecretApi:
    """A stand-in for SecretManagerServiceClient: NotFound on missing secret, versions list."""

    def __init__(self) -> None:
        self.secrets: dict[str, list[bytes]] = {}

    @staticmethod
    def _sid_from_secret_path(path: str) -> str:
        return path.split("/secrets/")[1].split("/versions/")[0]

    def access_secret_version(self, *, name: str) -> _FakeAccessResponse:
        sid = self._sid_from_secret_path(name)
        versions = self.secrets.get(sid)
        if not versions:
            raise _NotFound(f"no version for {sid}")
        return _FakeAccessResponse(payload=_FakePayload(data=versions[-1]))

    def add_secret_version(self, *, parent: str, payload: dict[str, bytes]) -> object:
        sid = parent.split("/secrets/")[1]
        if sid not in self.secrets:
            raise _NotFound(f"no secret {sid}")
        self.secrets[sid].append(payload["data"])
        return object()

    def create_secret(self, *, parent: str, secret_id: str, secret: dict[str, Any]) -> object:
        self.secrets.setdefault(secret_id, [])
        return object()


def test_google_backend_access_missing_returns_none() -> None:
    backend = GoogleSecretBackend(project_id="p", api=_FakeSecretApi())
    assert backend.access_latest("sid") is None


def test_google_backend_first_write_creates_secret_then_adds_version() -> None:
    api = _FakeSecretApi()
    backend = GoogleSecretBackend(project_id="p", api=api)
    backend.add_version("sid", b"hello")  # NotFound on add -> create -> add
    assert backend.access_latest("sid") == b"hello"


def test_google_backend_second_write_appends_version() -> None:
    api = _FakeSecretApi()
    backend = GoogleSecretBackend(project_id="p", api=api)
    backend.add_version("sid", b"one")
    backend.add_version("sid", b"two")
    assert backend.access_latest("sid") == b"two"
