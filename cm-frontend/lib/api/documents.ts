import { apiFetch } from "./client";
import type {
  DocumentDownloadUrlResponse,
  DocumentRead,
  DocumentRejectRequest,
  DocumentUploadUrlRequest,
  DocumentUploadUrlResponse,
  DocumentsListResponse,
} from "@/types/api";

// Client-onboarding documents data layer over the backend documents
// endpoints. Object content never proxies
// through this app: upload and download go direct to GCS via V4 signed
// URLs (see lib/api/upload.ts for the direct PUT). The signed-URL
// endpoints (upload-url, download-url) return 503 DOCUMENT_STORAGE_UNAVAILABLE
// when storage is not configured (local dev has no GCS); the caller renders
// a "document storage not configured" state rather than crashing. GET list
// is a pure DB read and works without GCS. Verify / reject are
// pure DB writes (CONFIGURE gate, same as the other document routes) and
// drive the documents all-verified fact the review gate requires.

function writeHeaders(): Record<string, string> {
  return { "Idempotency-Key": crypto.randomUUID() };
}

export const documentsApi = {
  list: (tenantId: string) =>
    apiFetch<DocumentsListResponse>(
      `/api/v1/tenants/${tenantId}/documents`,
    ),

  createUploadUrl: (tenantId: string, body: DocumentUploadUrlRequest) =>
    apiFetch<DocumentUploadUrlResponse>(
      `/api/v1/tenants/${tenantId}/documents/upload-url`,
      { method: "POST", body: JSON.stringify(body), headers: writeHeaders() },
    ),

  getDownloadUrl: (tenantId: string, documentId: string) =>
    apiFetch<DocumentDownloadUrlResponse>(
      `/api/v1/tenants/${tenantId}/documents/${documentId}/download-url`,
    ),

  remove: (tenantId: string, documentId: string) =>
    apiFetch<void>(
      `/api/v1/tenants/${tenantId}/documents/${documentId}`,
      { method: "DELETE", headers: writeHeaders() },
    ),

  verify: (tenantId: string, documentId: string) =>
    apiFetch<DocumentRead>(
      `/api/v1/tenants/${tenantId}/documents/${documentId}/verify`,
      { method: "POST", headers: writeHeaders() },
    ),

  reject: (tenantId: string, documentId: string, body: DocumentRejectRequest) =>
    apiFetch<DocumentRead>(
      `/api/v1/tenants/${tenantId}/documents/${documentId}/reject`,
      { method: "POST", body: JSON.stringify(body), headers: writeHeaders() },
    ),
};
