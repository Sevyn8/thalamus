import { apiFetch, qs } from "./client";
import type {
  OrgNodeChildrenResponse,
  OrgTreeResponse,
} from "@/types/api";
import type { components } from "@/types/openapi-generated";

export type OrgTreeParams = {
  // Backend caps depth at 6, with auto-truncation when total nodes
  // would exceed 1000. Default 2 in the hook layer matches the
  // existing OrgTree component's auto-expand behavior (top 2 levels
  // visible) and keeps the first-paint payload small.
  depth?: number;
};

export type OrgNodeChildrenParams = {
  offset?: number;
  limit?: number;
};

export type OrgNodeCreatePayload = components["schemas"]["OrgNodeCreateRequest"];
export type OrgNodePatchPayload = components["schemas"]["OrgNodePatchRequest"];
export type OrgNodeRead = components["schemas"]["OrgNodeRead"];

// Phase 5n.1 (reads) + Phase 5n.7 (writes): routes through
// lib/api/client.ts, whose base URL is resolved at runtime via
// runtime-config (/api/config). Permission tuple
// ADMIN.ORG_NODES.CONFIGURE.TENANT gates POST + PATCH (LD9 collapse,
// matches the Stores pattern from Finding #32).
export const orgNodesApi = {
  tree: (tenantId: string, params?: OrgTreeParams) =>
    apiFetch<OrgTreeResponse>(
      `/api/v1/tenants/${tenantId}/org-tree${qs(
        params as Record<string, unknown> | undefined,
      )}`,
    ),
  children: (
    tenantId: string,
    nodeId: string,
    params?: OrgNodeChildrenParams,
  ) =>
    apiFetch<OrgNodeChildrenResponse>(
      `/api/v1/tenants/${tenantId}/org-nodes/${nodeId}/children${qs(
        params as Record<string, unknown> | undefined,
      )}`,
    ),

  create: (tenantId: string, input: OrgNodeCreatePayload) =>
    apiFetch<OrgNodeRead>(`/api/v1/tenants/${tenantId}/org-tree`, {
      method: "POST",
      body: JSON.stringify(input),
      headers: {
        "Idempotency-Key": crypto.randomUUID(),
      },
    }),

  patch: (tenantId: string, nodeId: string, input: OrgNodePatchPayload) =>
    apiFetch<OrgNodeRead>(`/api/v1/tenants/${tenantId}/org-tree/${nodeId}`, {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: {
        "Idempotency-Key": crypto.randomUUID(),
      },
    }),
};
