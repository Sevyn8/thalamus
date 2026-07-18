import { apiFetch, qs } from "./client";
import type {
  TenantUser,
  TenantUserListResponse,
  TenantUserStatus,
} from "@/types/api";
import type { components } from "@/types/openapi-generated";

export type TenantUserListParams = {
  // Optional for Platform JWTs (omitting returns cross-tenant users).
  // For Tenant JWTs, backend RLS scopes regardless of param value.
  tenant_id?: string;
  status?: TenantUserStatus;
  search?: string;
  sort?: string;
  offset?: number;
  limit?: number;
};

export type TenantUserCreatePayload = components["schemas"]["TenantUserCreateRequest"];
export type TenantUserPatchPayload = components["schemas"]["TenantUserPatchRequest"];
export type RoleAssignmentItem = components["schemas"]["RoleAssignmentItem"];

// Phase 5n.1 (reads) + Phase 5n.8.1 (writes scaffold; 5n.8.2 + 5n.8.3
// consume create + patch).
//
// All four writes gate on the same multi-audience tuple
// `ADMIN.USERS.CONFIGURE.TENANT` per
// src/admin_backend/routers/v1/tenant_users.py:391-394 (create),
// 454-457 (patch), 519-522 (suspend), 575-578 (activate). PLATFORM
// passes via GLOBAL→TENANT cascade; OWNER passes via direct TENANT
// grant. No tuple split needed — same posture as Stores (Finding #32)
// and Org Nodes (Finding #35).
export const tenantUsersApi = {
  list: (params?: TenantUserListParams) =>
    apiFetch<TenantUserListResponse>(
      `/api/v1/tenant-users${qs(params as Record<string, unknown> | undefined)}`,
    ),

  get: (id: string) => apiFetch<TenantUser>(`/api/v1/tenant-users/${id}`),

  create: (input: TenantUserCreatePayload) =>
    apiFetch<TenantUser>(`/api/v1/tenant-users`, {
      method: "POST",
      body: JSON.stringify(input),
      headers: {
        "Idempotency-Key": crypto.randomUUID(),
      },
    }),

  patch: (id: string, input: TenantUserPatchPayload) =>
    apiFetch<TenantUser>(`/api/v1/tenant-users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: {
        "Idempotency-Key": crypto.randomUUID(),
      },
    }),

  activate: (id: string) =>
    apiFetch<TenantUser>(`/api/v1/tenant-users/${id}/activate`, {
      method: "POST",
      headers: {
        "Idempotency-Key": crypto.randomUUID(),
      },
    }),

  suspend: (id: string) =>
    apiFetch<TenantUser>(`/api/v1/tenant-users/${id}/suspend`, {
      method: "POST",
      headers: {
        "Idempotency-Key": crypto.randomUUID(),
      },
    }),
};
