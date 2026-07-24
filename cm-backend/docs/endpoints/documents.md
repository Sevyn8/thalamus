# Client Onboarding documents endpoints (Slice 3)

Tenant onboarding documents, all tenant-scoped under
`/api/v1/tenants/{tenant_id}/documents`. Every endpoint is gated
`ADMIN.TENANTS.CONFIGURE.GLOBAL` with `audience="PLATFORM"` (staff-driven
onboarding, D-12), the same gate as the Slice-2 wizard sections.

Object content never proxies through the backend: uploads and downloads go
direct to GCS via V4 signed URLs. The machine-readable contract is the
OpenAPI spec at `/api/v1/openapi.json` (regeneration is a tracked
follow-up); this file is the human-readable companion.

## Auth / gate

- Auth: `Authorization: Bearer <jwt>`.
- Gate: `ADMIN.TENANTS.CONFIGURE.GLOBAL`, `audience="PLATFORM"`. A TENANT
  JWT is rejected 403 `PLATFORM_AUDIENCE_REQUIRED` (Layer 1, before any DB
  read). A PLATFORM caller lacking the grant is 403 `PERMISSION_DENIED`.
- Cross-tenant / missing tenant: 404 `TENANT_NOT_FOUND` (RLS-as-404, D-17).

## Storage configuration

The signed-URL endpoints (`upload-url`, `download-url`) require storage to
be fully configured: BOTH `GCS_DOCUMENTS_BUCKET` and
`GCS_SIGNER_SERVICE_ACCOUNT_EMAIL`. The latter is required because Cloud
Run's keyless V4 signing (IAM signBlob) must be told which SA to sign as;
the runtime metadata credential cannot self-sign. When either is unset the
signer is not constructed and these endpoints return 503
`DOCUMENT_STORAGE_UNAVAILABLE` (an operational-capability signal, mirroring
`PROVISIONING_UNAVAILABLE`), never a raw GCS/signing exception. `list` /
`verify` / `reject` are pure DB operations. `delete` is DB-authoritative
and does best-effort object cleanup (see below); it does not 503 when
storage is unconfigured.

## Endpoints

### `POST /{tenant_id}/documents/upload-url` -> 201 `DocumentUploadUrlResponse`
Creates a `PENDING_REVIEW` document row and returns a V4 signed PUT URL the
client uses to upload the object directly to GCS.
- Body: `{document_type, file_name, content_type, file_size_bytes}`.
- `document_type` is validated against the active `document_type`
  `core.lookups` rows; invalid -> 422 `INVALID_LOOKUP_CODE`.
- `content_type` must be one of `application/pdf`, `image/png`,
  `image/jpeg`; otherwise 422 `INVALID_CONTENT_TYPE`.
- `file_size_bytes` must be <= 10485760 (10 MiB); otherwise 422
  `FILE_TOO_LARGE`.
- Response: `{document: DocumentRead, upload_url: str}`. The object key is
  `tenants/{tenant_id}/documents/{unique}/{sanitized_file_name}`; the
  stored `gcs_object_uri` is `gs://{bucket}/{object_key}`.

### `GET /{tenant_id}/documents` -> `DocumentsListResponse`
Lists the tenant's documents (newest first). `{items: [DocumentRead, ...]}`.

### `GET /{tenant_id}/documents/{document_id}/download-url` -> `DocumentDownloadUrlResponse`
Returns a short-expiry V4 signed GET URL for the object. 404
`DOCUMENT_NOT_FOUND` if the document is not visible for this tenant
(missing, RLS-filtered, or belonging to another tenant).

### `POST /{tenant_id}/documents/{document_id}/verify` -> `DocumentRead`
Marks the document `VERIFIED` and stamps `verified_by`/`verified_at`.
Allowed only from `PENDING_REVIEW`; otherwise 409 `INVALID_DOCUMENT_STATE`.

### `POST /{tenant_id}/documents/{document_id}/reject` -> `DocumentRead`
Marks the document `REJECTED`. Body: `{rejection_reason}` (required).
Allowed only from `PENDING_REVIEW`; otherwise 409 `INVALID_DOCUMENT_STATE`.

### `DELETE /{tenant_id}/documents/{document_id}` -> 204
Deletes the document. Allowed only while `PENDING_REVIEW`; a verified or
rejected document returns 409 `INVALID_DOCUMENT_STATE`. The DB row is
authoritative; the GCS object is deleted best-effort in the same request
(a signing/storage failure, or an object never uploaded, is logged and
does not fail the delete). When storage is unconfigured the delete is a
pure row delete.

## `DocumentRead` shape
```
{
  "id": "<uuid>",
  "document_type": "PAN_CARD",
  "file_name": "pan.pdf",
  "content_type": "application/pdf",
  "file_size_bytes": 1024,
  "verification_status": "PENDING_REVIEW",
  "verified_at": null,
  "rejection_reason": null,
  "created_at": "2026-07-24T00:00:00+00:00"
}
```
`gcs_object_uri` and the audit-actor columns are hidden (D-28 convention).

## Verification state machine

```
PENDING_REVIEW --verify--> VERIFIED   (terminal)
PENDING_REVIEW --reject--> REJECTED   (terminal, requires rejection_reason)
PENDING_REVIEW --delete--> (gone)
```
verify / reject / delete on a non-`PENDING_REVIEW` document -> 409
`INVALID_DOCUMENT_STATE`. The DDL CHECK
`ck_tenant_documents_verification_consistency` backstops the app state
machine (VERIFIED / REJECTED require `verified_by_user_id` + `verified_at`;
REJECTED requires `rejection_reason`).

## Onboarding-state review gate

`GET /{tenant_id}/onboarding`'s `sections_present.documents` is a
counts block (Slice 3 change from the Slice-2 bool):
```
"documents": {
  "total": 2, "pending_review": 0, "verified": 2, "rejected": 0,
  "all_verified": true
}
```
`all_verified` is true only when at least one document exists AND none are
`PENDING_REVIEW` or `REJECTED`. The wizard consumes this in Slice 6;
`complete-onboarding` is NOT gated on documents in this slice.

## Audit

Every write route emits exactly one audit event (success path,
`resource_type=TENANT`, routed to `tenant_activity_audit_logs`). Action
codes: `CREATE_DOCUMENT`, `VERIFY_DOCUMENT`, `REJECT_DOCUMENT`,
`DELETE_DOCUMENT`. The GET reads (`list`, `download-url`) are not audited.

## Implementation reference
- Router: `src/admin_backend/routers/v1/documents.py`.
- Repo: `src/admin_backend/repositories/documents.py`.
- GCS seam: `src/admin_backend/gcs.py` (`SignedUrlGenerator` Protocol +
  `GcsSignedUrlGenerator`).
- Schemas: `src/admin_backend/schemas/document.py`.
- Errors: `INVALID_CONTENT_TYPE`, `FILE_TOO_LARGE`, `DOCUMENT_NOT_FOUND`,
  `INVALID_DOCUMENT_STATE`, `DOCUMENT_STORAGE_UNAVAILABLE`,
  `INVALID_LOOKUP_CODE` in `src/admin_backend/errors.py`.
- Migration: `migrations/versions/b755e9d4081c_slice3_documents_verification.py`.
- Audit wiring: `AUDITED_ROUTES` + `_ACTION_LABELS` in
  `src/admin_backend/audit/emit.py`.
- Terraform: `infra/modules/gcs-tenant-documents` + `infra/envs/staging/main.tf`.
