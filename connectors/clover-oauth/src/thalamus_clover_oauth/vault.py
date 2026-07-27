"""GCP Secret Manager-backed token vault (one secret per tenant/source), with a version prune.

Layered exactly like ``thalamus_square_oauth.vault``: :class:`CloverTokenVault` holds all the
logic (naming + payload (de)serialize + read/write + the prune policy) behind the narrow
:class:`SecretBackend` Protocol, so it is fully unit-tested against an in-memory fake with no
network. :class:`GoogleSecretBackend` is the thin real adapter, itself driven through a
second narrow Protocol so tests fake the GCP client.

WHAT IS NEW HERE, AND WHY (D5). The Square lane appends versions and never prunes, which is
fine at its ~27-day rotation. Clover access tokens live 30 MINUTES, so a run-per-hour
connector rotates ~24 times per merchant per day and Secret Manager versions would grow
without bound. This vault therefore keeps the CURRENT and the PREVIOUS enabled version and
destroys anything older on every write. There is no precedent for version-lifecycle handling
anywhere else in this repo; this is the first.

WHY KEEPING TWO IS SAFE. The recovery credential (``previous_refresh_token``) lives INSIDE
the current version's payload, not in a superseded version, so pruning cannot destroy it.
The second version is kept purely as an operator escape hatch for a corrupt latest write.

IAM. ``destroy_version`` and ``list_enabled_versions`` need ``secretmanager.versions.destroy``
and ``secretmanager.versions.list``, which NO existing role in ``infra/`` grants — the
Square lane's ``squareTokenVaultRefresher`` custom role covers get/access/add only. A C-later
terraform slice must add them to the Clover runtime SA. Until then the prune degrades
loudly-but-safely: see :meth:`CloverTokenVault.write`.
"""

from __future__ import annotations

from typing import Any, Protocol, cast
from uuid import UUID

from google.api_core.exceptions import GoogleAPICallError, NotFound, RetryError

from dis_core.logging import get_logger
from thalamus_clover_oauth.naming import secret_id_for
from thalamus_clover_oauth.payload import CloverTokenSet

_SERVICE = "thalamus-clover-oauth"
_log = get_logger(_SERVICE)

# Versions to keep enabled after a write: the current one, plus one predecessor as an
# operator escape hatch. Anything older is destroyed.
KEEP_VERSIONS = 2

# The GCP failures the prune tolerates: a real API rejection (PermissionDenied when the SA
# lacks versions.destroy, FailedPrecondition on an already-destroyed version, NotFound on a
# racing prune) or an exhausted retry. Deliberately NOT `except Exception` — a TypeError or
# AttributeError in this path is a PROGRAMMING error and must surface, not be absorbed as
# though it were a transient GCP blip.
_PRUNE_TOLERATED = (GoogleAPICallError, RetryError)


class SecretBackend(Protocol):
    """The minimal secret store the vault needs, in the vault's own vocabulary."""

    def access_latest(self, secret_id: str) -> bytes | None:
        """The latest version's bytes, or None when the secret does not exist yet."""
        ...

    def add_version(self, secret_id: str, data: bytes) -> None:
        """Add a new version, creating the secret first if it does not exist."""
        ...

    def list_enabled_versions(self, secret_id: str) -> list[str]:
        """Enabled version resource names, NEWEST FIRST. Destroyed/disabled are excluded."""
        ...

    def destroy_version(self, version_name: str) -> None:
        """Permanently destroy one version by resource name."""
        ...


class CloverTokenVault:
    """Read/write a tenant/source token record as a Secret Manager secret version."""

    def __init__(self, backend: SecretBackend, *, keep_versions: int = KEEP_VERSIONS) -> None:
        self._backend = backend
        self._keep_versions = keep_versions

    def read(self, tenant_id: UUID, source_id: str) -> CloverTokenSet | None:
        """The current token record for the key, or None if never connected."""
        raw = self._backend.access_latest(secret_id_for(tenant_id, source_id))
        if raw is None:
            return None
        return CloverTokenSet.from_json(raw.decode("utf-8"))

    def write(self, tenant_id: UUID, source_id: str, token_set: CloverTokenSet) -> None:
        """Persist the record as a new version, then prune superseded versions (D5).

        The two steps have DIFFERENT failure postures, and the asymmetry is the point:

        - the ADD must succeed or raise. On Clover's single-use model a swallowed write
          means the rotation is lost and the merchant is one step from re-consent.
        - the PRUNE is best-effort. By the time it runs the token is already durable, so
          raising here would report a persistence failure that did not happen — and on this
          lane that misreport IS the lost-write scenario it would be claiming. A failed
          prune costs disk and an audit-noise version; a failed write costs a merchant.

        The prune's swallow is narrow (see ``_PRUNE_TOLERATED``) and logged at WARNING with
        the secret name and the offending version, because "versions accumulating forever"
        is otherwise invisible until someone hits a quota.
        """
        secret_id = secret_id_for(tenant_id, source_id)
        self._backend.add_version(secret_id, token_set.to_json().encode("utf-8"))
        self._prune(secret_id)

    def _prune(self, secret_id: str) -> None:
        """Destroy every enabled version older than the newest ``keep_versions``."""
        log = _log.bind(stage="token_vault", secret_id=secret_id)
        try:
            versions = self._backend.list_enabled_versions(secret_id)
        except _PRUNE_TOLERATED as exc:
            log.warning(
                "could not list secret versions to prune; versions will accumulate "
                f"(needs secretmanager.versions.list): {type(exc).__name__}"
            )
            return
        for version_name in versions[self._keep_versions :]:
            try:
                self._backend.destroy_version(version_name)
            except _PRUNE_TOLERATED as exc:
                log.warning(
                    f"could not destroy superseded secret version {version_name}; it will "
                    f"remain enabled (needs secretmanager.versions.destroy): {type(exc).__name__}"
                )


# ----- the real GCP adapter (driven through a narrow Protocol so tests fake it) -----


class _Payload(Protocol):
    @property
    def data(self) -> bytes: ...


class _AccessResponse(Protocol):
    @property
    def payload(self) -> _Payload: ...


class _Version(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def state(self) -> Any: ...


class _SecretApi(Protocol):
    """Exactly the SecretManagerServiceClient calls GoogleSecretBackend makes."""

    def access_secret_version(self, *, name: str) -> _AccessResponse: ...

    def add_secret_version(self, *, parent: str, payload: dict[str, bytes]) -> object: ...

    def create_secret(self, *, parent: str, secret_id: str, secret: dict[str, Any]) -> object: ...

    def list_secret_versions(self, *, parent: str) -> Any: ...

    def destroy_secret_version(self, *, name: str) -> object: ...


def _version_number(version_name: str) -> int:
    """The trailing integer of ``projects/P/secrets/S/versions/N``; 0 when unparseable.

    Sorting by this rather than by list order makes newest-first independent of whatever
    order the API returns, and an unparseable name sorts oldest so it prunes first rather
    than masquerading as current.
    """
    tail = version_name.rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else 0


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

    def list_enabled_versions(self, secret_id: str) -> list[str]:
        """Enabled version names, newest first. DESTROYED/DISABLED are filtered out so the
        keep-count is counted over usable versions only."""
        api = self._client()
        versions = api.list_secret_versions(parent=self._secret_path(secret_id))
        enabled = [v.name for v in versions if str(getattr(v.state, "name", v.state)) == "ENABLED"]
        return sorted(enabled, key=_version_number, reverse=True)

    def destroy_version(self, version_name: str) -> None:
        self._client().destroy_secret_version(name=version_name)
