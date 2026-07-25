import { apiFetch, qs } from "./client";
import type { ListResponse } from "./types";
import type { Tenant, TenantDetail, TenantStats, TenantTier } from "@/types/api";
import type { components } from "@/types/openapi-generated";

// Backend-truth: PATCH /tenants/{id} body. All fields optional;
// backend raises 422 EmptyPatchError if `model_dump(exclude_unset=True)`
// is empty (Phase 5n.5 / Step 6.11.2).
export type TenantPatchPayload = components["schemas"]["TenantPatchRequest"];

// Tenants list params trimmed to what the backend's GET /api/v1/tenants
// accepts (verified against deployed backend in Phase 4b Chunk 4 curl tests).
// Multi-status filter and tier-array were in earlier hand-typed versions
// but never reached the UI; removed to keep the type-checked surface
// honest.
//
// Phase 5c.partial-deploy.hotfix2: sort param added — Top Tenants
// dashboard panel calls tenantsApi.list({sort:
// "num_users_active_desc", limit: 10}) instead of the prior MSW-only
// /dashboard/top-tenants. Tight union per the 6+ documented sort
// keys in openapi.json (column-based + aggregate-based; aggregate
// keys use RLS-correct correlated subqueries server-side).
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

// Phase 5n.5 (2026-05-18): tenant writes wired against the real
// backend (Step 6.11.2 endpoints). All write surfaces use per-call
// Idempotency-Key per the 500-retry-with-two-intents pattern.
//
// Slice 6: the modal-era provision()/inputToPayload()/ProvisionTenantPayload
// were retired with ProvisionTenantModal; the onboarding wizard creates
// tenants via create() (a raw TenantCreateRequest, region incl. INDIA).
export const tenantsApi = {
  list: (params?: TenantListParams) =>
    apiFetch<ListResponse<Tenant>>(
      `/api/v1/tenants${qs(params as Record<string, unknown> | undefined)}`,
    ),
  get: (id: string) => apiFetch<TenantDetail>(`/api/v1/tenants/${id}`),
  stats: () => apiFetch<TenantStats>(`/api/v1/tenants/stats`),

  // Slice 6: complete onboarding (ONBOARDING -> TRIAL). 409
  // ONBOARDING_INCOMPLETE names the missing gate facts; 409
  // INVALID_STATE_TRANSITION if not ONBOARDING. Returns the TenantDetail
  // (status TRIAL) on success.
  completeOnboarding: (id: string) =>
    apiFetch<TenantDetail>(`/api/v1/tenants/${id}/complete-onboarding`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),

  // Slice 4: onboarding wizard POST. Takes a raw TenantCreateRequest
  // (region includes INDIA). The wizard builds the body from its own
  // schema. This is now the only tenant-create path (the modal-era
  // provision() adapter was retired in Slice 6).
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

  // Slice 5: get-or-create the tenant's Auth0 Organization (idempotent).
  // Auth0-side + (option a) persists tenants.auth0_org_id. 503
  // PROVISIONING_UNAVAILABLE when the Auth0 mgmt client is unconfigured
  // (local dev). First frontend wiring of this endpoint.
  provisionAuth0: (id: string) =>
    apiFetch<components["schemas"]["TenantOrgProvisionResult"]>(
      `/api/v1/tenants/${id}/provision-auth0`,
      { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() } },
    ),
};
