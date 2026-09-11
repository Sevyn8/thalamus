import { apiFetch, qs } from "./client";
import type { components } from "@/types/openapi-generated";

// Audit read endpoints. Cursor pagination — distinct shape from the
// offset `Pagination` envelope used elsewhere. `prev_cursor` is server-null
// in v0 (sequential next-only per the schema doc); the page-level
// cursor stack provides client-side back navigation.

export type AuditActivityListItem =
  components["schemas"]["AuditActivityListItem"];
export type AuditActivityDetail =
  components["schemas"]["AuditActivityDetail"];
export type AuditActivitiesListResponse =
  components["schemas"]["AuditActivitiesListResponse"];
export type AuditResultType = components["schemas"]["AuditResultType"];
export type ActorUserType = components["schemas"]["ActorUserType"];

// Scope-of-row enum (synthesised server-side at query time per the
// AuditActivityListItem schema doc). Distinct from PermissionScope —
// rows are tagged PLATFORM or TENANT by which audit table they came
// from, not by the caller's grant scope.
export type AuditRowScope = "PLATFORM" | "TENANT";

// Resource-type filter is documented by the backend as an open string
// vocabulary; the values below are the current emitters. Unknown
// values return 0 rows (no 422). Frontend keeps the union typed for
// autocomplete safety but the wire shape is plain `string`.
export type AuditResourceType =
  | "TENANT"
  | "TENANT_USER"
  | "ROLE"
  | "MODULE_ACCESS"
  | "ORG_NODE"
  | "STORE";

export type AuditListParams = {
  cursor?: string;
  limit?: number;
  from?: string;
  to?: string;
  status?: AuditResultType;
  tenant_id?: string;
  scope?: AuditRowScope;
  search?: string;
  // Filter by resource type.
  resource_type?: AuditResourceType;
  // Filter by acting user uuid. Enables the per-user Activity
  // sub-section in PlatformUserDetailDrawer and
  // TenantUserDetailDrawer.
  actor_user_id?: string;
};

export const auditApi = {
  list: (params?: AuditListParams) =>
    apiFetch<AuditActivitiesListResponse>(
      `/api/v1/audit/activities${qs(
        params as Record<string, unknown> | undefined,
      )}`,
    ),

  get: (id: string) =>
    apiFetch<AuditActivityDetail>(`/api/v1/audit/activities/${id}`),
};
