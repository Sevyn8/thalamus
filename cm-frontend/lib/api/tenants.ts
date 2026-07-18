import { apiFetch, qs } from "./client";
import type { ListResponse } from "./types";
import type { Tenant, TenantDetail, TenantStats, TenantTier } from "@/types/api";
import type { ProvisionTenantInput } from "@/lib/schemas/provision-tenant";
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

// Server-side payload sent on POST. Mirrors the DDL-paired as_of_date pattern;
// the form maintains user-facing fields, this function shapes them for the API.
export type ProvisionTenantPayload = {
  name: string;
  display_code?: string | null;
  region: "US" | "EU";
  tier: "ENTERPRISE" | "MID_MARKET" | "SMB" | "SINGLE_STORE";
  industry:
    | "CONVENIENCE_FUEL"
    | "CONVENIENCE"
    | "GROCERY"
    | "HYPERMART"
    | "SPECIALITY_GROCERY"
    | "ORGANIC_GROCERY";
  country: string;
  primary_contact_name: string;
  contact_email: string;
  number_of_stores: number;
  number_of_stores_as_of_date: string;
  monthly_revenue_usd?: string | null;
  monthly_revenue_as_of_date?: string | null;
};

function inputToPayload(input: ProvisionTenantInput): ProvisionTenantPayload {
  const today = new Date().toISOString().slice(0, 10);
  const display = input.display_code?.trim();
  const revenue = input.monthly_revenue_usd?.trim();
  return {
    name: input.name.trim(),
    display_code: display ? display.toLowerCase() : null,
    region: input.region,
    tier: input.tier,
    industry: input.industry,
    country: input.country.trim(),
    primary_contact_name: input.primary_contact_name.trim(),
    contact_email: input.contact_email.trim().toLowerCase(),
    number_of_stores: input.number_of_stores,
    number_of_stores_as_of_date: today,
    monthly_revenue_usd: revenue ? revenue : null,
    monthly_revenue_as_of_date: revenue ? today : null,
  };
}

export type ProvisionTenantErrorBody = {
  code: string;
  message: string;
  details?: { field_errors?: Record<string, string[]>; field?: string };
  request_id: string;
};

// Phase 5n.5 (2026-05-18): tenant writes wired against the real
// backend (Step 6.11.2 endpoints). All 4 write surfaces (POST + PATCH
// + activate + suspend) use per-call Idempotency-Key per the
// 500-retry-with-two-intents pattern.
export const tenantsApi = {
  list: (params?: TenantListParams) =>
    apiFetch<ListResponse<Tenant>>(
      `/api/v1/tenants${qs(params as Record<string, unknown> | undefined)}`,
    ),
  get: (id: string) => apiFetch<TenantDetail>(`/api/v1/tenants/${id}`),
  stats: () => apiFetch<TenantStats>(`/api/v1/tenants/stats`),

  provision: (input: ProvisionTenantInput) =>
    apiFetch<Tenant>(`/api/v1/tenants`, {
      method: "POST",
      body: JSON.stringify(inputToPayload(input)),
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
};
