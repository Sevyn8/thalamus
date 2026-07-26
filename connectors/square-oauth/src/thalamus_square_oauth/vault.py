"""GCP Secret Manager-backed token vault (one secret per tenant/source).

:class:`SquareTokenVault` holds all the logic (naming + payload (de)serialize + the
read/write contract) behind the narrow :class:`SecretBackend` Protocol, so it is fully
unit-tested against an in-memory fake with no network. :class:`GoogleSecretBackend` is the
thin real adapter over ``SecretManagerServiceClient``; it too is driven through a narrow
Protocol so tests fake the client instead of reaching GCP.
"""

from __future__ import annotations

from typing import Any, Protocol, cast
from uuid import UUID

from google.api_core.exceptions import NotFound

from thalamus_square_oauth.naming import secret_id_for
from thalamus_square_oauth.payload import SquareTokenSet


class SecretBackend(Protocol):
    """The minimal secret store the vault needs, in the vault's own vocabulary."""

    def access_latest(self, secret_id: str) -> bytes | None:
        """The latest version's bytes, or None when the secret does not exist yet."""
        ...

    def add_version(self, secret_id: str, data: bytes) -> None:
        """Add a new version, creating the secret first if it does not exist."""
        ...


class SquareTokenVault:
    """Read/write a tenant/source token set as a Secret Manager secret version."""

    def __init__(self, backend: SecretBackend) -> None:
        self._backend = backend

    def read(self, tenant_id: UUID, source_id: str) -> SquareTokenSet | None:
        """The current token set for the key, or None if never connected."""
        raw = self._backend.access_latest(secret_id_for(tenant_id, source_id))
        if raw is None:
            return None
        return SquareTokenSet.from_json(raw.decode("utf-8"))

    def write(self, tenant_id: UUID, source_id: str, token_set: SquareTokenSet) -> None:
        """Persist the token set as a new version (creates the secret on first write)."""
        self._backend.add_version(secret_id_for(tenant_id, source_id), token_set.to_json().encode("utf-8"))


# ----- the real GCP adapter (driven through a narrow Protocol so tests fake it) -----


class _Payload(Protocol):
    @property
    def data(self) -> bytes: ...


class _AccessResponse(Protocol):
    @property
    def payload(self) -> _Payload: ...


class _SecretApi(Protocol):
    """Exactly the SecretManagerServiceClient calls GoogleSecretBackend makes."""

    def access_secret_version(self, *, name: str) -> _AccessResponse: ...

    def add_secret_version(self, *, parent: str, payload: dict[str, bytes]) -> object: ...

    def create_secret(self, *, parent: str, secret_id: str, secret: dict[str, Any]) -> object: ...


class GoogleSecretBackend:
    """SecretBackend over ``SecretManagerServiceClient``. Maps NotFound to None on read and
    creates-then-adds on first write. Automatic replication.

    The real client is built LAZILY on first use (not at construction), so wiring this into
    a pipeline never resolves ADC credentials until an actual secret call is made — matching
    the credential-lazy posture of the other data-plane clients. Tests inject ``api``."""

    def __init__(self, *, project_id: str, api: _SecretApi | None = None) -> None:
        self._project_id = project_id
        self._api = api

    def _client(self) -> _SecretApi:
        if self._api is None:
            from google.cloud import secretmanager

            self._api = cast(_SecretApi, secretmanager.SecretManagerServiceClient())
        return self._api

    def _project_path(self) -> str:
        return f"projects/{self._project_id}"

    def _secret_path(self, secret_id: str) -> str:
        return f"projects/{self._project_id}/secrets/{secret_id}"

    def access_latest(self, secret_id: str) -> bytes | None:
        name = f"{self._secret_path(secret_id)}/versions/latest"
        api = self._client()
        try:
            response = api.access_secret_version(name=name)
        except NotFound:
            return None
        return response.payload.data

    def add_version(self, secret_id: str, data: bytes) -> None:
        api = self._client()
        try:
            api.add_secret_version(parent=self._secret_path(secret_id), payload={"data": data})
        except NotFound:
            api.create_secret(
                parent=self._project_path(),
                secret_id=secret_id,
                secret={"replication": {"automatic": {}}},
            )
            api.add_secret_version(parent=self._secret_path(secret_id), payload={"data": data})
