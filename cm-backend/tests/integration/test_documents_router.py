"""Integration tests for the tenant-documents endpoints.

A fake ``SignedUrlGenerator`` is injected on ``app.state.gcs_signer`` (no
GCS, no network); the TestClient is built WITHOUT the lifespan context
manager so the injected fake survives (the lifespan would set it from
settings). Covers the upload-url / list / download-url / verify / reject /
delete matrix, the storage-unconfigured 503 guard, validation 422s
(content-type, size, document_type), the verification state machine 409s,
the onboarding-state documents block + all_verified truth table, and audit
emission for every write.
"""
from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from admin_backend.auth.context import AuthContext
from admin_backend.auth.stub import StubAuthClient
from admin_backend.auth.testing import make_test_jwt
from admin_backend.config import Settings, get_settings
from admin_backend.db.session import get_tenant_session
from admin_backend.main import create_app

pytestmark = pytest.mark.asyncio


class _FakeSigner:
    """Fake SignedUrlGenerator: records calls, returns deterministic URLs.
    Satisfies the ``SignedUrlGenerator`` Protocol structurally."""

    def __init__(self, bucket: str = "test-bucket", *, delete_fails: bool = False) -> None:
        self._bucket = bucket
        self.upload_calls: list[dict[str, Any]] = []
        self.download_calls: list[dict[str, Any]] = []
        self.delete_calls: list[str] = []
        self._delete_fails = delete_fails

    @property
    def bucket(self) -> str:
        return self._bucket

    def generate_upload_url(
        self, *, object_name: str, content_type: str, expiry_seconds: int
    ) -> str:
        self.upload_calls.append(
            {
                "object_name": object_name,
                "content_type": content_type,
                "expiry_seconds": expiry_seconds,
            }
        )
        return f"https://signed.example/PUT/{object_name}"

    def generate_download_url(
        self, *, object_name: str, expiry_seconds: int
    ) -> str:
        self.download_calls.append(
            {"object_name": object_name, "expiry_seconds": expiry_seconds}
        )
        return f"https://signed.example/GET/{object_name}"

    def delete_object(self, *, object_name: str) -> None:
        if self._delete_fails:
            raise RuntimeError("simulated GCS delete failure")
        self.delete_calls.append(object_name)


def _make_client(
    settings: Settings, engine: Any, session_factory: Any, *, signer: Any
) -> TestClient:
    app = create_app()
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.auth_client = StubAuthClient(settings)
    app.state.gcs_signer = signer
    return TestClient(app)


@pytest.fixture
def signer() -> _FakeSigner:
    return _FakeSigner()


@pytest.fixture
def app_client(
    settings: Settings, engine: Any, session_factory: Any, signer: _FakeSigner
) -> TestClient:
    return _make_client(settings, engine, session_factory, signer=signer)


def _auth(jwt: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {jwt}"}


def _tenant_jwt(settings: Settings, tenant_id: UUID) -> str:
    return make_test_jwt(
        settings, user_id=uuid.uuid4(), user_type="TENANT", tenant_id=tenant_id
    )


def _upload_body(
    *,
    document_type: str = "PAN_CARD",
    file_name: str = "pan.pdf",
    content_type: str = "application/pdf",
    file_size_bytes: int = 1024,
) -> dict[str, Any]:
    return {
        "document_type": document_type,
        "file_name": file_name,
        "content_type": content_type,
        "file_size_bytes": file_size_bytes,
    }


def _upload(
    client: TestClient, jwt: str, tenant_id: UUID, **overrides: Any
) -> Any:
    return client.post(
        f"/api/v1/tenants/{tenant_id}/documents/upload-url",
        json=_upload_body(**overrides),
        headers=_auth(jwt),
    )


async def _audit_actions(
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
    tenant_id: UUID,
) -> list[str]:
    schema = get_settings().db_schema
    async for session in get_tenant_session(platform_auth, session_factory):
        result = await session.execute(
            text(
                f"SELECT action, result_type FROM "
                f"{schema}.tenant_activity_audit_logs "
                "WHERE tenant_id = :tid ORDER BY timestamp, id"
            ),
            {"tid": tenant_id},
        )
        return [f"{r.action}:{r.result_type}" for r in result]
    raise AssertionError("unreachable")  # pragma: no cover


# ===========================================================================
# Upload URL (UP)
# ===========================================================================


async def test_up1_upload_url_happy_creates_pending_and_signs(
    app_client, signer, super_admin_jwt, make_tenant, cleanup_documents,
    session_factory, platform_auth,
) -> None:
    """LOAD-BEARING: upload-url mints a signed PUT + creates a
    PENDING_REVIEW row + emits one CREATE_DOCUMENT audit event."""
    tenant = await make_tenant(name="UP1")
    cleanup_documents.append(tenant.id)

    resp = _upload(app_client, super_admin_jwt, tenant.id)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert set(body.keys()) == {"document", "upload_url"}
    doc = body["document"]
    assert doc["document_type"] == "PAN_CARD"
    assert doc["verification_status"] == "PENDING_REVIEW"
    assert doc["file_size_bytes"] == 1024
    assert doc["verified_at"] is None
    assert body["upload_url"].startswith("https://signed.example/PUT/")

    # signer called once with the tenant-scoped object key + content type.
    assert len(signer.upload_calls) == 1
    call = signer.upload_calls[0]
    assert call["object_name"].startswith(
        f"tenants/{tenant.id}/documents/"
    )
    assert call["content_type"] == "application/pdf"
    assert call["expiry_seconds"] == 900

    actions = await _audit_actions(session_factory, platform_auth, tenant.id)
    assert actions == ["CREATE_DOCUMENT:SUCCESS"]


async def test_up2_invalid_content_type_returns_422(
    app_client, super_admin_jwt, make_tenant, cleanup_documents,
) -> None:
    tenant = await make_tenant(name="UP2")
    cleanup_documents.append(tenant.id)
    resp = _upload(
        app_client, super_admin_jwt, tenant.id, content_type="image/gif"
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "INVALID_CONTENT_TYPE"


async def test_up3_file_too_large_returns_422(
    app_client, super_admin_jwt, make_tenant, cleanup_documents,
) -> None:
    tenant = await make_tenant(name="UP3")
    cleanup_documents.append(tenant.id)
    resp = _upload(
        app_client,
        super_admin_jwt,
        tenant.id,
        file_size_bytes=10 * 1024 * 1024 + 1,
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "FILE_TOO_LARGE"


async def test_up4_invalid_document_type_returns_422(
    app_client, super_admin_jwt, make_tenant, cleanup_documents,
) -> None:
    tenant = await make_tenant(name="UP4")
    cleanup_documents.append(tenant.id)
    resp = _upload(
        app_client, super_admin_jwt, tenant.id, document_type="NOT_A_TYPE"
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "INVALID_LOOKUP_CODE"
    assert "document_type" in resp.json()["message"]


async def test_up5_unknown_tenant_returns_404(
    app_client, super_admin_jwt,
) -> None:
    resp = _upload(app_client, super_admin_jwt, uuid.uuid4())
    assert resp.status_code == 404
    assert resp.json()["code"] == "TENANT_NOT_FOUND"


async def test_up6_tenant_jwt_denied_403(
    app_client, settings,
) -> None:
    jwt = _tenant_jwt(settings, uuid.uuid4())
    resp = _upload(app_client, jwt, uuid.uuid4())
    assert resp.status_code == 403
    assert resp.json()["code"] == "PLATFORM_AUDIENCE_REQUIRED"


async def test_up7_storage_unconfigured_returns_503(
    settings, engine, session_factory, super_admin_jwt, make_tenant,
    cleanup_documents,
) -> None:
    """LOAD-BEARING: GCS bucket unset -> the endpoint fails loudly with a
    clear 503 (project error envelope), not a raw GCS exception."""
    tenant = await make_tenant(name="UP7")
    cleanup_documents.append(tenant.id)
    client = _make_client(settings, engine, session_factory, signer=None)
    resp = _upload(client, super_admin_jwt, tenant.id)
    assert resp.status_code == 503
    assert resp.json()["code"] == "DOCUMENT_STORAGE_UNAVAILABLE"


# ===========================================================================
# List (LS)
# ===========================================================================


async def test_ls1_list_returns_created_documents(
    app_client, super_admin_jwt, make_tenant, cleanup_documents,
) -> None:
    tenant = await make_tenant(name="LS1")
    cleanup_documents.append(tenant.id)
    _upload(app_client, super_admin_jwt, tenant.id, file_name="a.pdf")
    _upload(app_client, super_admin_jwt, tenant.id, file_name="b.pdf")
    resp = app_client.get(
        f"/api/v1/tenants/{tenant.id}/documents", headers=_auth(super_admin_jwt)
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 2
    assert {i["verification_status"] for i in items} == {"PENDING_REVIEW"}


async def test_ls2_unknown_tenant_returns_404(
    app_client, super_admin_jwt,
) -> None:
    resp = app_client.get(
        f"/api/v1/tenants/{uuid.uuid4()}/documents",
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "TENANT_NOT_FOUND"


# ===========================================================================
# Download URL (DL)
# ===========================================================================


async def test_dl1_download_url_happy(
    app_client, signer, super_admin_jwt, make_tenant, cleanup_documents,
) -> None:
    tenant = await make_tenant(name="DL1")
    cleanup_documents.append(tenant.id)
    doc_id = _upload(app_client, super_admin_jwt, tenant.id).json()["document"][
        "id"
    ]
    resp = app_client.get(
        f"/api/v1/tenants/{tenant.id}/documents/{doc_id}/download-url",
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["download_url"].startswith("https://signed.example/GET/")
    assert len(signer.download_calls) == 1
    assert signer.download_calls[0]["expiry_seconds"] == 300


async def test_dl2_unknown_document_returns_404(
    app_client, super_admin_jwt, make_tenant, cleanup_documents,
) -> None:
    tenant = await make_tenant(name="DL2")
    cleanup_documents.append(tenant.id)
    resp = app_client.get(
        f"/api/v1/tenants/{tenant.id}/documents/{uuid.uuid4()}/download-url",
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "DOCUMENT_NOT_FOUND"


async def test_dl3_cross_tenant_document_returns_404(
    app_client, super_admin_jwt, make_tenant, cleanup_documents,
) -> None:
    """LOAD-BEARING: a document id from tenant A is not reachable under
    tenant B's path (tenant-scoped WHERE, not just RLS)."""
    tenant_a = await make_tenant(name="DL3-A")
    tenant_b = await make_tenant(name="DL3-B")
    cleanup_documents.append(tenant_a.id)
    cleanup_documents.append(tenant_b.id)
    doc_id = _upload(app_client, super_admin_jwt, tenant_a.id).json()[
        "document"
    ]["id"]
    resp = app_client.get(
        f"/api/v1/tenants/{tenant_b.id}/documents/{doc_id}/download-url",
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "DOCUMENT_NOT_FOUND"


async def test_dl4_storage_unconfigured_returns_503(
    settings, engine, session_factory, app_client, super_admin_jwt,
    make_tenant, cleanup_documents,
) -> None:
    tenant = await make_tenant(name="DL4")
    cleanup_documents.append(tenant.id)
    # Create with the configured client, then request download with an
    # unconfigured one.
    doc_id = _upload(app_client, super_admin_jwt, tenant.id).json()["document"][
        "id"
    ]
    client = _make_client(settings, engine, session_factory, signer=None)
    resp = client.get(
        f"/api/v1/tenants/{tenant.id}/documents/{doc_id}/download-url",
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 503
    assert resp.json()["code"] == "DOCUMENT_STORAGE_UNAVAILABLE"


# ===========================================================================
# Verify (VF)
# ===========================================================================


async def test_vf1_verify_pending_succeeds(
    app_client, super_admin_jwt, make_tenant, cleanup_documents,
    session_factory, platform_auth,
) -> None:
    tenant = await make_tenant(name="VF1")
    cleanup_documents.append(tenant.id)
    doc_id = _upload(app_client, super_admin_jwt, tenant.id).json()["document"][
        "id"
    ]
    resp = app_client.post(
        f"/api/v1/tenants/{tenant.id}/documents/{doc_id}/verify",
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verification_status"] == "VERIFIED"
    assert body["verified_at"] is not None

    actions = await _audit_actions(session_factory, platform_auth, tenant.id)
    assert actions == ["CREATE_DOCUMENT:SUCCESS", "VERIFY_DOCUMENT:SUCCESS"]


async def test_vf2_verify_already_verified_returns_409(
    app_client, super_admin_jwt, make_tenant, cleanup_documents,
) -> None:
    tenant = await make_tenant(name="VF2")
    cleanup_documents.append(tenant.id)
    doc_id = _upload(app_client, super_admin_jwt, tenant.id).json()["document"][
        "id"
    ]
    app_client.post(
        f"/api/v1/tenants/{tenant.id}/documents/{doc_id}/verify",
        headers=_auth(super_admin_jwt),
    )
    resp = app_client.post(
        f"/api/v1/tenants/{tenant.id}/documents/{doc_id}/verify",
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "INVALID_DOCUMENT_STATE"


async def test_vf3_verify_unknown_document_returns_404(
    app_client, super_admin_jwt, make_tenant, cleanup_documents,
) -> None:
    tenant = await make_tenant(name="VF3")
    cleanup_documents.append(tenant.id)
    resp = app_client.post(
        f"/api/v1/tenants/{tenant.id}/documents/{uuid.uuid4()}/verify",
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "DOCUMENT_NOT_FOUND"


# ===========================================================================
# Reject (RJ)
# ===========================================================================


async def test_rj1_reject_pending_with_reason_succeeds(
    app_client, super_admin_jwt, make_tenant, cleanup_documents,
    session_factory, platform_auth,
) -> None:
    tenant = await make_tenant(name="RJ1")
    cleanup_documents.append(tenant.id)
    doc_id = _upload(app_client, super_admin_jwt, tenant.id).json()["document"][
        "id"
    ]
    resp = app_client.post(
        f"/api/v1/tenants/{tenant.id}/documents/{doc_id}/reject",
        json={"rejection_reason": "blurry scan"},
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verification_status"] == "REJECTED"
    assert body["rejection_reason"] == "blurry scan"

    actions = await _audit_actions(session_factory, platform_auth, tenant.id)
    assert actions == ["CREATE_DOCUMENT:SUCCESS", "REJECT_DOCUMENT:SUCCESS"]


async def test_rj2_reject_without_reason_returns_422(
    app_client, super_admin_jwt, make_tenant, cleanup_documents,
) -> None:
    tenant = await make_tenant(name="RJ2")
    cleanup_documents.append(tenant.id)
    doc_id = _upload(app_client, super_admin_jwt, tenant.id).json()["document"][
        "id"
    ]
    resp = app_client.post(
        f"/api/v1/tenants/{tenant.id}/documents/{doc_id}/reject",
        json={},
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 422


async def test_rj3_reject_already_rejected_returns_409(
    app_client, super_admin_jwt, make_tenant, cleanup_documents,
) -> None:
    tenant = await make_tenant(name="RJ3")
    cleanup_documents.append(tenant.id)
    doc_id = _upload(app_client, super_admin_jwt, tenant.id).json()["document"][
        "id"
    ]
    for _ in range(1):
        app_client.post(
            f"/api/v1/tenants/{tenant.id}/documents/{doc_id}/reject",
            json={"rejection_reason": "first"},
            headers=_auth(super_admin_jwt),
        )
    resp = app_client.post(
        f"/api/v1/tenants/{tenant.id}/documents/{doc_id}/reject",
        json={"rejection_reason": "second"},
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "INVALID_DOCUMENT_STATE"


# ===========================================================================
# Delete (DE)
# ===========================================================================


async def test_de1_delete_pending_succeeds(
    app_client, signer, super_admin_jwt, make_tenant, cleanup_documents,
    session_factory, platform_auth,
) -> None:
    tenant = await make_tenant(name="DE1")
    cleanup_documents.append(tenant.id)
    doc_id = _upload(app_client, super_admin_jwt, tenant.id).json()["document"][
        "id"
    ]
    resp = app_client.request(
        "DELETE",
        f"/api/v1/tenants/{tenant.id}/documents/{doc_id}",
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 204, resp.text
    # Row is gone.
    listing = app_client.get(
        f"/api/v1/tenants/{tenant.id}/documents", headers=_auth(super_admin_jwt)
    ).json()["items"]
    assert listing == []
    # Best-effort GCS object cleanup fired in the same request.
    assert len(signer.delete_calls) == 1
    assert signer.delete_calls[0].startswith(f"tenants/{tenant.id}/documents/")

    actions = await _audit_actions(session_factory, platform_auth, tenant.id)
    assert actions == ["CREATE_DOCUMENT:SUCCESS", "DELETE_DOCUMENT:SUCCESS"]


async def test_de2_delete_verified_returns_409(
    app_client, super_admin_jwt, make_tenant, cleanup_documents,
) -> None:
    """LOAD-BEARING: delete is PENDING_REVIEW-only; a verified document
    cannot be deleted."""
    tenant = await make_tenant(name="DE2")
    cleanup_documents.append(tenant.id)
    doc_id = _upload(app_client, super_admin_jwt, tenant.id).json()["document"][
        "id"
    ]
    app_client.post(
        f"/api/v1/tenants/{tenant.id}/documents/{doc_id}/verify",
        headers=_auth(super_admin_jwt),
    )
    resp = app_client.request(
        "DELETE",
        f"/api/v1/tenants/{tenant.id}/documents/{doc_id}",
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "INVALID_DOCUMENT_STATE"


async def test_de3_delete_unknown_returns_404(
    app_client, super_admin_jwt, make_tenant, cleanup_documents,
) -> None:
    tenant = await make_tenant(name="DE3")
    cleanup_documents.append(tenant.id)
    resp = app_client.request(
        "DELETE",
        f"/api/v1/tenants/{tenant.id}/documents/{uuid.uuid4()}",
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "DOCUMENT_NOT_FOUND"


async def test_de4_delete_row_only_when_storage_unconfigured(
    app_client, settings, engine, session_factory, super_admin_jwt,
    make_tenant, cleanup_documents,
) -> None:
    """Storage unconfigured (signer None): delete is a pure row delete
    (no 503), object cleanup is skipped. Create with the configured
    client, delete with the unconfigured one."""
    tenant = await make_tenant(name="DE4")
    cleanup_documents.append(tenant.id)
    doc_id = _upload(app_client, super_admin_jwt, tenant.id).json()["document"][
        "id"
    ]
    client = _make_client(settings, engine, session_factory, signer=None)
    resp = client.request(
        "DELETE",
        f"/api/v1/tenants/{tenant.id}/documents/{doc_id}",
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 204, resp.text
    listing = app_client.get(
        f"/api/v1/tenants/{tenant.id}/documents", headers=_auth(super_admin_jwt)
    ).json()["items"]
    assert listing == []


async def test_de5_object_delete_failure_does_not_fail_row_delete(
    settings, engine, session_factory, super_admin_jwt, make_tenant,
    cleanup_documents,
) -> None:
    """LOAD-BEARING: a GCS object-delete failure must not fail the row
    delete (best-effort; logged)."""
    tenant = await make_tenant(name="DE5")
    cleanup_documents.append(tenant.id)
    failing = _FakeSigner(delete_fails=True)
    client = _make_client(settings, engine, session_factory, signer=failing)
    doc_id = _upload(client, super_admin_jwt, tenant.id).json()["document"][
        "id"
    ]
    resp = client.request(
        "DELETE",
        f"/api/v1/tenants/{tenant.id}/documents/{doc_id}",
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 204, resp.text
    listing = client.get(
        f"/api/v1/tenants/{tenant.id}/documents", headers=_auth(super_admin_jwt)
    ).json()["items"]
    assert listing == []


# ===========================================================================
# Onboarding-state documents block + all_verified truth table (OBD)
# ===========================================================================


def _documents_block(app_client: TestClient, jwt: str, tenant_id: UUID) -> Any:
    body = app_client.get(
        f"/api/v1/tenants/{tenant_id}/onboarding", headers=_auth(jwt)
    ).json()
    return body["sections_present"]["documents"]


async def test_obd1_no_documents_all_verified_false(
    app_client, super_admin_jwt, make_tenant, cleanup_documents,
) -> None:
    tenant = await make_tenant(name="OBD1")
    cleanup_documents.append(tenant.id)
    block = _documents_block(app_client, super_admin_jwt, tenant.id)
    assert block == {
        "total": 0, "pending_review": 0, "verified": 0,
        "rejected": 0, "all_verified": False,
    }


async def test_obd2_one_pending_all_verified_false(
    app_client, super_admin_jwt, make_tenant, cleanup_documents,
) -> None:
    tenant = await make_tenant(name="OBD2")
    cleanup_documents.append(tenant.id)
    _upload(app_client, super_admin_jwt, tenant.id)
    block = _documents_block(app_client, super_admin_jwt, tenant.id)
    assert block["total"] == 1
    assert block["pending_review"] == 1
    assert block["all_verified"] is False


async def test_obd3_one_verified_all_verified_true(
    app_client, super_admin_jwt, make_tenant, cleanup_documents,
) -> None:
    """LOAD-BEARING: all_verified is true only when >=1 doc and none
    pending/rejected."""
    tenant = await make_tenant(name="OBD3")
    cleanup_documents.append(tenant.id)
    doc_id = _upload(app_client, super_admin_jwt, tenant.id).json()["document"][
        "id"
    ]
    app_client.post(
        f"/api/v1/tenants/{tenant.id}/documents/{doc_id}/verify",
        headers=_auth(super_admin_jwt),
    )
    block = _documents_block(app_client, super_admin_jwt, tenant.id)
    assert block["total"] == 1
    assert block["verified"] == 1
    assert block["all_verified"] is True


async def test_obd4_verified_plus_pending_all_verified_false(
    app_client, super_admin_jwt, make_tenant, cleanup_documents,
) -> None:
    tenant = await make_tenant(name="OBD4")
    cleanup_documents.append(tenant.id)
    doc_id = _upload(app_client, super_admin_jwt, tenant.id).json()["document"][
        "id"
    ]
    app_client.post(
        f"/api/v1/tenants/{tenant.id}/documents/{doc_id}/verify",
        headers=_auth(super_admin_jwt),
    )
    _upload(app_client, super_admin_jwt, tenant.id, file_name="second.pdf")
    block = _documents_block(app_client, super_admin_jwt, tenant.id)
    assert block["total"] == 2
    assert block["verified"] == 1
    assert block["pending_review"] == 1
    assert block["all_verified"] is False


async def test_obd5_verified_plus_rejected_all_verified_false(
    app_client, super_admin_jwt, make_tenant, cleanup_documents,
) -> None:
    tenant = await make_tenant(name="OBD5")
    cleanup_documents.append(tenant.id)
    d1 = _upload(app_client, super_admin_jwt, tenant.id).json()["document"][
        "id"
    ]
    app_client.post(
        f"/api/v1/tenants/{tenant.id}/documents/{d1}/verify",
        headers=_auth(super_admin_jwt),
    )
    d2 = _upload(
        app_client, super_admin_jwt, tenant.id, file_name="second.pdf"
    ).json()["document"]["id"]
    app_client.post(
        f"/api/v1/tenants/{tenant.id}/documents/{d2}/reject",
        json={"rejection_reason": "no"},
        headers=_auth(super_admin_jwt),
    )
    block = _documents_block(app_client, super_admin_jwt, tenant.id)
    assert block["total"] == 2
    assert block["verified"] == 1
    assert block["rejected"] == 1
    assert block["all_verified"] is False
