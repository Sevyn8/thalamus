import { apiFetch, qs } from "./client";
import type { ListResponse } from "./types";
import type { Tenant, TenantDetail, TenantStats, TenantTier } from "@/types/api";
import type { components } from "@/types/openapi-generated";

// Backend-truth: PATCH /tenants/{id} body. All fields optional;
// backend raises 422 EmptyPatchError if `model_dump(exclude_unset=True)`
// is empty.
export type TenantPatchPayload = components["schemas"]["TenantPatchRequest"];

// Tenants list params trimmed to what the backend's GET /api/v1/tenants
// accepts, keeping the type-checked surface honest.
//
// The `sort` param serves the Top Tenants dashboard panel
// (tenantsApi.list({sort: "num_users_active_desc", limit: 10})).
// Tight union per the documented sort keys in openapi.json
// (column-based + aggregate-based; aggregate keys use RLS-correct
// correlated subqueries server-side).
export type TenantSortKey =
  | "created_at_asc"
  | "created_at_desc"
  | "name_asc"
  | "name_desc"
  | "tier_asc"
  | "tier_desc"
  | "num_users_active_asc"
  | "num_users_active_desc"
  | "num_stores_asc"
  | "num_stores_desc";

export type TenantListParams = {
  tier?: TenantTier;
  search?: string;
  sort?: TenantSortKey;
  offset?: number;
  limit?: number;
};

// All write surfaces send a per-call Idempotency-Key so a retried
// request after a 500 cannot register two intents. The onboarding
// wizard creates tenants via create() (a raw TenantCreateRequest,
// region incl. INDIA).
export const tenantsApi = {
  list: (params?: TenantListParams) =>
    apiFetch<ListResponse<Tenant>>(
      `/api/v1/tenants${qs(params as Record<string, unknown> | undefined)}`,
    ),
  get: (id: string) => apiFetch<TenantDetail>(`/api/v1/tenants/${id}`),
  stats: () => apiFetch<TenantStats>(`/api/v1/tenants/stats`),

  // Complete onboarding (ONBOARDING -> TRIAL). 409
  // ONBOARDING_INCOMPLETE names the missing gate facts; 409
  // INVALID_STATE_TRANSITION if not ONBOARDING. Returns the TenantDetail
  // (status TRIAL) on success.
  completeOnboarding: (id: string) =>
    apiFetch<TenantDetail>(`/api/v1/tenants/${id}/complete-onboarding`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),

  // Onboarding wizard POST. Takes a raw TenantCreateRequest (region
  // includes INDIA). The wizard builds the body from its own schema.
  // This is the only tenant-create path.
  create: (body: components["schemas"]["TenantCreateRequest"]) =>
    apiFetch<TenantDetail>(`/api/v1/tenants`, {
      method: "POST",
      body: JSON.stringify(body),
      headers: {
        "Idempotency-Key": crypto.randomUUID(),
      },
    }),

  patch: (id: string, input: TenantPatchPayload) =>
    apiFetch<TenantDetail>(`/api/v1/tenants/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: {
        "Idempotency-Key": crypto.randomUUID(),
      },
    }),

  activate: (id: string) =>
    apiFetch<TenantDetail>(`/api/v1/tenants/${id}/activate`, {
      method: "POST",
      headers: {
        "Idempotency-Key": crypto.randomUUID(),
      },
    }),

  suspend: (id: string) =>
    apiFetch<TenantDetail>(`/api/v1/tenants/${id}/suspend`, {
      method: "POST",
      headers: {
        "Idempotency-Key": crypto.randomUUID(),
      },
    }),

  // Get-or-create the tenant's Auth0 Organization (idempotent).
  // Auth0-side, and persists tenants.auth0_org_id. 503
  // PROVISIONING_UNAVAILABLE when the Auth0 mgmt client is
  // unconfigured (local dev).
  provisionAuth0: (id: string) =>
    apiFetch<components["schemas"]["TenantOrgProvisionResult"]>(
      `/api/v1/tenants/${id}/provision-auth0`,
      { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() } },
    ),
};
