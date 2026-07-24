"""Unit tests for the GCS signed-URL seam (Slice 3).

Two layers:

  * Pure object-key / URI helpers (no GCS, no network).
  * Real V4 signing OFFLINE: an in-memory RSA service-account credential
    signs locally, so ``GcsSignedUrlGenerator`` is exercised end to end
    without any network. This is the "credentials model that makes V4
    signing unit-testable" the plan committed to: on Cloud Run the signer
    uses keyless IAM signBlob (network), but the seam accepts an injected
    private-key credential that signs offline for tests.
"""
from __future__ import annotations

from uuid import UUID

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.cloud import storage
from google.oauth2 import service_account

from admin_backend.config import Settings
from admin_backend.errors import DocumentStorageUnavailableError
from admin_backend.gcs import (
    ALLOWED_CONTENT_TYPES,
    MAX_FILE_SIZE_BYTES,
    GcsSignedUrlGenerator,
    build_document_object_name,
    build_gcs_signer,
    build_gs_uri,
    object_name_from_uri,
    sanitize_file_name,
)

_TENANT = UUID("11111111-1111-1111-1111-111111111111")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_constants() -> None:
    assert ALLOWED_CONTENT_TYPES == (
        "application/pdf",
        "image/png",
        "image/jpeg",
    )
    assert MAX_FILE_SIZE_BYTES == 10 * 1024 * 1024


def test_sanitize_file_name() -> None:
    assert sanitize_file_name("Acme Certificate.pdf") == "Acme_Certificate.pdf"
    assert sanitize_file_name("../../etc/passwd") == "etc_passwd"
    # Each isolated unsafe char becomes its own underscore (runs collapse
    # to one); internal underscores are not stripped.
    assert sanitize_file_name("a b/c*d?.png") == "a_b_c_d_.png"
    # All-unsafe / empty -> stable non-empty fallback.
    assert sanitize_file_name("///") == "file"
    assert sanitize_file_name("") == "file"


def test_build_document_object_name_deterministic_with_unique() -> None:
    name = build_document_object_name(_TENANT, "PAN Card.pdf", unique="abc123")
    assert name == f"tenants/{_TENANT}/documents/abc123/PAN_Card.pdf"


def test_build_document_object_name_unique_varies() -> None:
    a = build_document_object_name(_TENANT, "x.pdf")
    b = build_document_object_name(_TENANT, "x.pdf")
    assert a != b  # fresh uuid4 per call
    assert a.startswith(f"tenants/{_TENANT}/documents/")


def test_gs_uri_roundtrip() -> None:
    uri = build_gs_uri("my-bucket", "tenants/x/documents/u/f.pdf")
    assert uri == "gs://my-bucket/tenants/x/documents/u/f.pdf"
    assert (
        object_name_from_uri(uri, "my-bucket")
        == "tenants/x/documents/u/f.pdf"
    )
    # Wrong bucket prefix -> returns input unchanged (defensive).
    assert object_name_from_uri(uri, "other") == uri


# ---------------------------------------------------------------------------
# Offline V4 signing with an in-memory service-account credential
# ---------------------------------------------------------------------------


def _offline_credentials() -> service_account.Credentials:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    info = {
        "type": "service_account",
        "project_id": "test-project",
        "private_key_id": "test-kid",
        "private_key": pem,
        "client_email": "signer@test-project.iam.gserviceaccount.com",
        "client_id": "1",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    return service_account.Credentials.from_service_account_info(info)


def _signer() -> GcsSignedUrlGenerator:
    settings = Settings(gcs_documents_bucket="my-bucket")  # type: ignore[call-arg]
    creds = _offline_credentials()
    client = storage.Client(project="test-project", credentials=creds)
    return GcsSignedUrlGenerator(settings, credentials=creds, client=client)


def test_generate_upload_url_offline_v4() -> None:
    url = _signer().generate_upload_url(
        object_name="tenants/t/documents/u/f.pdf",
        content_type="application/pdf",
        expiry_seconds=900,
    )
    assert url.startswith(
        "https://storage.googleapis.com/my-bucket/"
        "tenants/t/documents/u/f.pdf?"
    )
    assert "X-Goog-Algorithm=GOOG4-RSA-SHA256" in url
    assert "X-Goog-Signature=" in url
    assert "X-Goog-Expires=900" in url


def test_generate_download_url_offline_v4() -> None:
    url = _signer().generate_download_url(
        object_name="tenants/t/documents/u/f.pdf",
        expiry_seconds=300,
    )
    assert "my-bucket/tenants/t/documents/u/f.pdf" in url
    assert "X-Goog-Algorithm=GOOG4-RSA-SHA256" in url
    assert "X-Goog-Signature=" in url
    assert "X-Goog-Expires=300" in url


def test_bucket_property() -> None:
    assert _signer().bucket == "my-bucket"


def test_construction_requires_bucket() -> None:
    settings = Settings()  # type: ignore[call-arg]  # gcs_documents_bucket None
    with pytest.raises(DocumentStorageUnavailableError):
        GcsSignedUrlGenerator(settings)


# ---------------------------------------------------------------------------
# build_gcs_signer loud-config guard: BOTH bucket AND signer SA email
# required for the production (keyless) signer. Missing either -> None ->
# the document endpoints return 503 DOCUMENT_STORAGE_UNAVAILABLE.
# ---------------------------------------------------------------------------


def test_build_gcs_signer_none_when_bucket_unset() -> None:
    settings = Settings(  # type: ignore[call-arg]
        gcs_signer_service_account_email="signer@p.iam.gserviceaccount.com"
    )
    assert build_gcs_signer(settings) is None


def test_build_gcs_signer_none_when_signer_email_unset() -> None:
    # Bucket set but signer SA email unset: keyless V4 signing would fail
    # at request time, so the signer is not built -> loud 503, not a raw
    # signing error. Same guard posture as the missing-bucket case.
    settings = Settings(gcs_documents_bucket="b")  # type: ignore[call-arg]
    assert build_gcs_signer(settings) is None
