import { apiFetch, qs } from "./client";
import type { components } from "@/types/openapi-generated";

export type MePermissionsResponse =
  components["schemas"]["MePermissionsResponse"];
export type MeCanDoResponse = components["schemas"]["MeCanDoResponse"];

// Clients for the /me/* family. All requests route through
// lib/api/client.ts, whose base URL is resolved at runtime via
// runtime-config (/api/config).
//
// canDo query params are enum-validated server-side (422 on invalid).
// Pass `target_anchor` only as an ltree path (org_nodes.path, e.g.
// "tnt_acme.bu_hq"). NOT a UUID — hyphens are not valid ltree label
// chars. Pass undefined for "any org_node under the caller's scope
// satisfies."
//
// The runtime guard below fail-fasts in the browser if a non-ltree
// string slips through. It mirrors the backend's Pydantic validator
// (src/admin_backend/routers/v1/me.py), which returns HTTP 422
// server-side; failing fast client-side avoids the round-trip. Both
// layers defend the cast.
//
// Backend stamps maxLength=1024; not mirrored client-side (YAGNI —
// no realistic org-tree depth approaches the cap).

const LTREE_LABEL = /^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$/;

export type CanDoParams = {
  module: string;
  resource: string;
  action: string;
  scope: string;
  // Optional ltree path (e.g. "tnt_acme.bu_hq"). NOT a UUID. Omit
  // for tenant-level gates.
  target_anchor?: string;
};

export const meApi = {
  permissions: () =>
    apiFetch<MePermissionsResponse>(`/api/v1/me/permissions`),
  canDo: (params: CanDoParams) => {
    if (
      params.target_anchor !== undefined &&
      !LTREE_LABEL.test(params.target_anchor)
    ) {
      throw new Error(
        `meApi.canDo: target_anchor must be an ltree path (e.g. "tnt_acme.bu_hq"), got ${JSON.stringify(params.target_anchor)}. Omit the arg for tenant-level gates.`,
      );
    }
    return apiFetch<MeCanDoResponse>(
      `/api/v1/me/can-do${qs(params as Record<string, unknown>)}`,
    );
  },
};
