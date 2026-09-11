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

// All four writes (create, patch, suspend, activate) gate on the same
// multi-audience tuple `ADMIN.USERS.CONFIGURE.TENANT` in
// src/admin_backend/routers/v1/tenant_users.py. PLATFORM passes via
// GLOBAL→TENANT cascade; OWNER passes via direct TENANT grant. No
// tuple split needed — same posture as Stores and Org Nodes.
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

  // Provision the user's Auth0 identity (idempotent, Auth0-side;
  // writes nothing to CM). 503 when mgmt client / db-connection unset.
  provisionAuth0: (id: string) =>
    apiFetch<components["schemas"]["TenantUserProvisionResult"]>(
      `/api/v1/tenant-users/${id}/provision-auth0`,
      { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() } },
    ),

  // Send the invitation email (sets invited_at). 409
  // USER_NOT_PROVISIONED if no Auth0 identity yet; 503 if email/ticket
  // unconfigured. The wizard sequence always provisions first, so 409
  // should be unreachable through the UI.
  sendInvitation: (id: string) =>
    apiFetch<TenantUser>(`/api/v1/tenant-users/${id}/send-invitation`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),
};
