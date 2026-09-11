import { apiFetch, qs } from "./client";
import type {
  PermissionListResponse,
  PermissionMatrixResponse,
  RoleAssignmentsResponse,
  RoleListResponse,
  RolePermissionsResponse,
  UserRoleAssignmentStatus,
} from "@/types/api";
import type { components } from "@/types/openapi-generated";

// RBAC catalog + role detail/edit clients. Routes through
// lib/api/client.ts, whose base URL is resolved at runtime via
// runtime-config (/api/config).

export type RoleDetail = components["schemas"]["RoleDetail"];
export type RoleUpdateRequest = components["schemas"]["RoleUpdateRequest"];
export type PermissionDetail = components["schemas"]["PermissionDetail"];

export type RoleListParams = {
  status?: "ACTIVE" | "INACTIVE" | "ARCHIVED";
  is_system?: boolean;
  q?: string;
  sort?: "name_asc" | "name_desc" | "created_at_asc" | "created_at_desc";
  offset?: number;
  limit?: number;
};

export type PermissionListParams = {
  module?: string;
  scope?: "GLOBAL" | "TENANT" | "STORE";
  sort?: "module_asc" | "code_asc" | "code_desc";
  offset?: number;
  limit?: number;
};

// Role-assignments query params. `platform_user_id` and
// `tenant_user_id` are audience-specific; the bare `user_id` param
// is silently ignored server-side.
export type RoleAssignmentsParams = {
  role_id?: string;
  platform_user_id?: string;
  tenant_user_id?: string;
  tenant_id?: string;
  org_node_id?: string;
  status?: UserRoleAssignmentStatus;
  sort?: string;
  offset?: number;
  limit?: number;
};

export const rolesApi = {
  list: (params?: RoleListParams) =>
    apiFetch<RoleListResponse>(
      `/api/v1/roles${qs(params as Record<string, unknown> | undefined)}`,
    ),

  // Cross-audience requests return
  // 404 from the backend; consumers should handle ROLE_NOT_FOUND
  // gracefully (e.g., a TENANT JWT navigating to a PLATFORM role's
  // detail URL).
  getPermissions: (roleId: string) =>
    apiFetch<RolePermissionsResponse>(
      `/api/v1/roles/${roleId}/permissions`,
    ),

  // Self-contained role detail for the edit screen. Includes held
  // permissions plus the `available_permissions` catalogue delta —
  // frontend renders the edit modal from one URL. TENANT-audience
  // roles have GLOBAL-scope rows filtered out of
  // `available_permissions` server-side.
  detail: (roleId: string) =>
    apiFetch<RoleDetail>(`/api/v1/roles/${roleId}`),

  // Role update. PLATFORM-only by construction — gated by
  // ADMIN.ROLES.OVERRIDE.GLOBAL (audience-scope coherence excludes
  // TENANT roles). `permission_ids`
  // is replace-set semantics: backend diffs against current grants
  // and DELETEs/INSERTs accordingly. Unknown error codes surface as
  // raw messages; known codes the modal special-cases:
  // LAST_OVERRIDE_HOLDER (409), SUPER_ADMIN_PROTECTED (409),
  // AUDIENCE_SCOPE_MISMATCH (422), INVALID_PERMISSION_ID (422),
  // EMPTY_PATCH (422 — defensive).
  update: (roleId: string, patch: RoleUpdateRequest) =>
    apiFetch<RoleDetail>(`/api/v1/roles/${roleId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
      headers: {
        "Idempotency-Key": crypto.randomUUID(),
      },
    }),

  permissions: (params?: PermissionListParams) =>
    apiFetch<PermissionListResponse>(
      `/api/v1/permissions${qs(params as Record<string, unknown> | undefined)}`,
    ),

  matrix: () =>
    apiFetch<PermissionMatrixResponse>(`/api/v1/permission-matrix`),

  assignments: (params?: RoleAssignmentsParams) =>
    apiFetch<RoleAssignmentsResponse>(
      `/api/v1/role-assignments${qs(params as Record<string, unknown> | undefined)}`,
    ),
};
