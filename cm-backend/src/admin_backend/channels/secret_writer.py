"""Writing a tenant's channel credential into Secret Manager, and pruning what it replaced.

BEHIND A PROTOCOL, so the whole write path is drivable offline with a fake and the test suite
never reaches Google. Same posture and same reason as ``Auth0ManagementClient`` and
``SendGridEmailSender``: the seam is what lets the ordering, the failure modes and the prune be
tested at all.

=================================================================================================
THE VALUE GOES IN AND NEVER COMES BACK OUT
=================================================================================================
There is no read method on this Protocol, deliberately. CM writes a tenant's credential and has
no reason to see it again: the form replaces the whole set rather than editing fields, the row
records the NAME, and the eventual reader is the adapter in axon-sender under its own service
account. The IAM role this service holds therefore omits ``secretmanager.versions.access``, which
``tokenVaultWriter`` carries and this does not. A method that could read it back would make that
narrowing pointless, and a value that cannot be read cannot be logged, echoed or returned.

=================================================================================================
THE PRUNE IS NOT OPTIONAL AND IS NOT FREE
=================================================================================================
Every save adds a version. Without a prune, every superseded credential a tenant has ever entered
stays live in the vault forever, readable by anything holding the reader role. dis-ui-server's
``tokenVaultWriter`` records both halves of this trap: without ``versions.list`` and
``versions.destroy`` the write succeeds and the prune fails with PermissionDenied so versions
accumulate silently behind a healthy-looking connect; with the permissions but no prune call they
accumulate just as silently.

So this destroys every ENABLED version except the one just added, and it reports how many it
destroyed so a caller can assert the prune actually ran. A prune that silently does nothing is
indistinguishable from one that works, which is why the count is returned rather than logged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from admin_backend.errors import ServerError

if TYPE_CHECKING:  # pragma: no cover - import-time only for type checking
    from admin_backend.config import Settings

__all__ = [
    "ChannelSecretWriter",
    "ChannelSecretWriterProtocol",
    "SecretWriteError",
]


class SecretWriteError(ServerError):
    """The vault write failed. Surfaces as a generic 500 to the caller.

    A ServerError rather than a ClientError: the tenant's input was fine, the platform's
    dependency was not. Per the project's error model every ServerError responds with the generic
    INTERNAL_ERROR envelope, so no detail about Secret Manager, the project, or the secret's name
    reaches the response body. The detail goes to the log through ``internal_message``.
    """


@runtime_checkable
class ChannelSecretWriterProtocol(Protocol):
    """Store one credential blob under one name, and prune what it replaced.

    Two operations rather than one because the caller must be able to tell them apart: the write
    is what the tenant's save depends on, and the prune is housekeeping whose failure must not
    lose a credential the tenant just entered successfully.
    """

    def write(self, secret_id: str, payload: bytes) -> str:
        """Create the secret if absent, add ``payload`` as a version, return the version name."""
        ...

    def prune(self, secret_id: str, keep_version_name: str) -> int:
        """Destroy every enabled version except ``keep_version_name``. Return how many."""
        ...


class ChannelSecretWriter:
    """The real client. Constructed only when a project id is configured.

    IMPORTED LAZILY inside the methods rather than at module import. cm-backend's test suite and
    its mypy run must not require google-cloud-secret-manager to be importable in every context,
    and the lifespan constructs this only when configured, so a deployment that has not enabled
    channels never touches the library at all.
    """

    def __init__(self, settings: Settings) -> None:
        project_id = settings.channels_secrets_project_id
        if not project_id:
            raise SecretWriteError(
                internal_message=(
                    "ChannelSecretWriter constructed without CHANNELS_SECRETS_PROJECT_ID; the "
                    "lifespan is meant to leave it unconstructed instead."
                )
            )
        self._project_id: str = project_id
        self._client: object | None = None

    def _api(self) -> Any:
        from google.cloud import secretmanager

        if self._client is None:
            self._client = secretmanager.SecretManagerServiceClient()
        return self._client

    @property
    def _parent(self) -> str:
        return f"projects/{self._project_id}"

    def write(self, secret_id: str, payload: bytes) -> str:
        """Create-if-absent, then add a version.

        CREATE IS IDEMPOTENT BY CATCHING AlreadyExists rather than by listing first. A
        list-then-create is a read followed by a write with a gap in between, and two saves racing
        through that gap both see "absent" and one of them fails anyway. Catching the conflict is
        the same outcome with no gap.
        """
        from google.api_core import exceptions as gexc
        from google.cloud import secretmanager

        api = self._api()
        try:
            try:
                api.create_secret(
                    request={
                        "parent": self._parent,
                        "secret_id": secret_id,
                        "secret": {"replication": {"automatic": {}}},
                    }
                )
            except gexc.AlreadyExists:
                # The tenant has configured this channel before. Expected, not an error.
                pass

            version = api.add_secret_version(
                request={
                    "parent": f"{self._parent}/secrets/{secret_id}",
                    "payload": secretmanager.SecretPayload(data=payload),
                }
            )
        except Exception as exc:  # noqa: BLE001 - every provider failure is the same outcome here
            # THE MESSAGE NAMES THE SECRET AND NEVER THE PAYLOAD. A credential echoed into Cloud
            # Logging is a credential in Cloud Logging for the bucket's retention.
            raise SecretWriteError(
                internal_message=f"secret write failed for {secret_id}: {type(exc).__name__}"
            ) from exc
        return str(version.name)

    def prune(self, secret_id: str, keep_version_name: str) -> int:
        """Destroy every enabled version except the one just written. See the module docstring."""
        from google.api_core import exceptions as gexc

        api = self._api()
        destroyed = 0
        try:
            for version in api.list_secret_versions(
                request={"parent": f"{self._parent}/secrets/{secret_id}"}
            ):
                if version.name == keep_version_name:
                    continue
                if str(version.state) != "SecretVersion.State.ENABLED" and "ENABLED" not in str(
                    version.state
                ):
                    # Already destroyed or disabled; destroying again is an error, not a no-op.
                    continue
                try:
                    api.destroy_secret_version(request={"name": version.name})
                    destroyed += 1
                except gexc.FailedPrecondition:
                    # Raced with another prune. The version is gone, which is the desired state.
                    continue
        except Exception as exc:  # noqa: BLE001
            raise SecretWriteError(
                internal_message=f"secret prune failed for {secret_id}: {type(exc).__name__}"
            ) from exc
        return destroyed
