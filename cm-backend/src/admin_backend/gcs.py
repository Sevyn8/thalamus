"""GCS signed-URL generation for tenant documents.

A ``runtime_checkable`` ``SignedUrlGenerator`` Protocol plus a concrete
``GcsSignedUrlGenerator`` wrapping ``google-cloud-storage``, mirroring the
``EmailSender`` / ``Auth0ManagementClient`` seams: the document handlers
depend on the Protocol and inject a fake in tests (no network, no real
GCS). Constructed once in the lifespan, guarded on
``settings.gcs_documents_bucket``; when unset the handlers raise
``DocumentStorageUnavailableError`` (503) rather than a raw GCS exception.

V4 signing credential model (verified against code: CM has no GCP
credential wiring today):

  * Offline (unit tests): construct with a ``credentials`` object that
    carries a private key (an in-memory ``service_account.Credentials``).
    ``blob.generate_signed_url(version="v4", ...)`` then signs LOCALLY
    with that private key. No network.
  * Cloud Run (production, keyless): construct with ``credentials=None``
    and a ``service_account_email``. Signing uses the IAM ``signBlob``
    API (the runtime SA needs ``roles/iam.serviceAccountTokenCreator`` on
    itself). This path makes a network call and is exercised only in a
    real deploy, NOT in unit tests. The seam (Protocol + fake) is the
    testable boundary; the offline-credentials path additionally lets the
    real signing code run in a unit test.

Object naming is a pure helper (``build_document_object_name``) so the
key layout is unit-testable independently of any GCS call.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import timedelta
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4

from google.cloud import storage

from admin_backend.config import Settings
from admin_backend.errors import DocumentStorageUnavailableError

# Allowlisted upload content types. The router validates against
# this set before minting an upload URL.
ALLOWED_CONTENT_TYPES: tuple[str, ...] = (
    "application/pdf",
    "image/png",
    "image/jpeg",
)

# Maximum upload size: 10 MiB.
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10485760

_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_file_name(file_name: str) -> str:
    """Reduce an uploaded file name to a safe object-path segment.

    Collapses any run of characters outside ``[A-Za-z0-9._-]`` to a
    single underscore and trims leading/trailing separators. Empty or
    all-unsafe input becomes ``"file"`` so the object path always has a
    non-empty final segment.
    """
    cleaned = _UNSAFE_NAME_CHARS.sub("_", file_name).strip("._-")
    return cleaned or "file"


def build_document_object_name(
    tenant_id: UUID, file_name: str, *, unique: str | None = None
) -> str:
    """Return the object key for a tenant document.

    Layout: ``tenants/{tenant_id}/documents/{unique}/{sanitized_name}``.
    ``unique`` isolates each upload so two files with the same name never
    collide and so the object key is independent of the DB row id (the PK
    is DB-assigned via ``uuidv7()`` per D-21 and is not known before
    INSERT). ``unique`` defaults to a fresh ``uuid4().hex``; tests pass a
    fixed value for determinism.
    """
    token = unique if unique is not None else uuid4().hex
    return (
        f"tenants/{tenant_id}/documents/{token}/{sanitize_file_name(file_name)}"
    )


def object_name_from_uri(uri: str, bucket: str) -> str:
    """Extract the object key from a stored ``gs://{bucket}/{key}`` URI.

    Falls back to returning ``uri`` unchanged if it does not carry the
    expected ``gs://{bucket}/`` prefix (defensive; the repo always writes
    the canonical form).
    """
    prefix = f"gs://{bucket}/"
    if uri.startswith(prefix):
        return uri[len(prefix):]
    return uri


def build_gs_uri(bucket: str, object_name: str) -> str:
    """Canonical ``gs://{bucket}/{object_name}`` URI stored on the row."""
    return f"gs://{bucket}/{object_name}"


@runtime_checkable
class SignedUrlGenerator(Protocol):
    """The signed-URL operations the document handlers depend on. The
    handlers and their tests inject a fake satisfying this Protocol."""

    @property
    def bucket(self) -> str: ...

    def generate_upload_url(
        self, *, object_name: str, content_type: str, expiry_seconds: int
    ) -> str: ...

    def generate_download_url(
        self, *, object_name: str, expiry_seconds: int
    ) -> str: ...

    def delete_object(self, *, object_name: str) -> None: ...


class GcsSignedUrlGenerator:
    """V4 signed-URL generator backed by ``google-cloud-storage``.

    Construction requires ``settings.gcs_documents_bucket`` (guarded);
    the lifespan only builds this when the bucket is set. ``credentials``
    and ``client`` are injectable so unit tests drive real offline V4
    signing with an in-memory service-account credential.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        credentials: object | None = None,
        client: storage.Client | None = None,
        token_provider: Callable[[], str] | None = None,
    ) -> None:
        bucket = settings.gcs_documents_bucket
        if not bucket:
            raise DocumentStorageUnavailableError(
                "GcsSignedUrlGenerator requires gcs_documents_bucket"
            )
        self._bucket_name = bucket
        self._service_account_email = settings.gcs_signer_service_account_email
        self._credentials = credentials
        # Keyless-signing access-token source. None -> the real runtime
        # path (google.auth.default + refresh). Tests inject a fake so the
        # keyless branch is exercisable without network / metadata server.
        self._token_provider = token_provider
        if client is not None:
            self._client = client
        elif credentials is not None:
            self._client = storage.Client(credentials=credentials)
        else:
            # Cloud Run: application default credentials (metadata server).
            self._client = storage.Client()

    def _runtime_access_token(self) -> str:
        """Return an OAuth access token for the runtime service account,
        used by the keyless V4 signing path (IAM signBlob).

        The metadata credential on Cloud Run holds no private key, so the
        google-cloud-storage signer falls back to demanding one unless BOTH
        ``service_account_email`` AND ``access_token`` are passed to
        ``generate_signed_url`` (verified in the vendored
        ``_signing.generate_signed_url_v4``). This mints that token by
        refreshing application-default credentials.

        Per-call refresh is intentional at this volume (document
        upload/download is low-frequency, staff-driven); a token cache is a
        deliberate follow-up, not shipped here.
        """
        if self._token_provider is not None:
            return self._token_provider()
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default()
        # google.auth's base Credentials.refresh is not fully typed.
        creds.refresh(google.auth.transport.requests.Request())  # type: ignore[no-untyped-call]
        token = getattr(creds, "token", None)
        if not token:
            raise DocumentStorageUnavailableError(
                "could not obtain a runtime access token for signed-URL "
                "generation"
            )
        return str(token)

    @property
    def bucket(self) -> str:
        return self._bucket_name

    def _signed_url(
        self,
        *,
        object_name: str,
        method: str,
        expiry_seconds: int,
        content_type: str | None,
    ) -> str:
        blob = self._client.bucket(self._bucket_name).blob(object_name)
        kwargs: dict[str, object] = {
            "version": "v4",
            "expiration": timedelta(seconds=expiry_seconds),
            "method": method,
        }
        if content_type is not None:
            kwargs["content_type"] = content_type
        if self._credentials is not None:
            # Offline signing with a private-key credential.
            kwargs["credentials"] = self._credentials
        elif self._service_account_email is not None:
            # Keyless signing on Cloud Run via IAM signBlob. BOTH
            # service_account_email AND access_token must be passed, or the
            # library falls back to demanding a private key on the metadata
            # credential (which it lacks). Applies to uploads and downloads.
            kwargs["service_account_email"] = self._service_account_email
            kwargs["access_token"] = self._runtime_access_token()
        url: str = blob.generate_signed_url(**kwargs)
        return url

    def generate_upload_url(
        self, *, object_name: str, content_type: str, expiry_seconds: int
    ) -> str:
        return self._signed_url(
            object_name=object_name,
            method="PUT",
            expiry_seconds=expiry_seconds,
            content_type=content_type,
        )

    def generate_download_url(
        self, *, object_name: str, expiry_seconds: int
    ) -> str:
        return self._signed_url(
            object_name=object_name,
            method="GET",
            expiry_seconds=expiry_seconds,
            content_type=None,
        )

    def delete_object(self, *, object_name: str) -> None:
        """Delete the object from the bucket. Used by the best-effort
        cleanup on document delete; callers must tolerate failure."""
        self._client.bucket(self._bucket_name).blob(object_name).delete()


def build_gcs_signer(settings: Settings) -> GcsSignedUrlGenerator | None:
    """Construct the production signer, or None when storage is not fully
    configured (the document endpoints then return 503
    DOCUMENT_STORAGE_UNAVAILABLE at request time).

    BOTH ``gcs_documents_bucket`` AND ``gcs_signer_service_account_email``
    are required. The Cloud Run keyless V4 signing path (IAM signBlob)
    passes the signer SA email to ``generate_signed_url``; the runtime
    metadata credential cannot self-sign a V4 URL, so without the email
    signing would raise a raw error at request time. Returning None here
    turns that into the same loud, explicit 503 the missing-bucket case
    produces. The offline unit path (an injected private-key credential)
    bypasses this helper and constructs GcsSignedUrlGenerator directly.
    """
    if not settings.gcs_documents_bucket:
        return None
    if not settings.gcs_signer_service_account_email:
        return None
    return GcsSignedUrlGenerator(settings)
