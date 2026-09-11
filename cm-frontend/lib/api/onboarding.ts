import { ApiError, apiFetch } from "./client";
import type {
  BillingProfileRead,
  BillingProfileUpsertRequest,
  ContactsRead,
  ContactsReplaceRequest,
  LegalProfileRead,
  LegalProfileUpsertRequest,
  OnboardingPatchRequest,
  OnboardingStateResponse,
  TaxRegistrationsRead,
  TaxRegistrationsReplaceRequest,
} from "@/types/api";

// Client-onboarding wizard data layer over the backend section + state
// endpoints. All tenant-scoped under /tenants/{tenant_id}; every route
// is PLATFORM-audience-gated server-side.
//
// The 1:1 section GETs (legal-profile, billing-profile) return 404
// SECTION_NOT_FOUND when the section has not been saved yet (distinct from
// TENANT_NOT_FOUND). The wizard treats "not saved yet" as an empty form,
// so those getters translate that specific 404 to null and let any other
// error propagate.
//
// Writes carry a per-call Idempotency-Key, matching the tenants write
// convention (harmless for the naturally-idempotent upsert / full-replace
// section writes; keeps the write surface uniform).

function writeHeaders(): Record<string, string> {
  return { "Idempotency-Key": crypto.randomUUID() };
}

async function getOrNull<T>(path: string): Promise<T | null> {
  try {
    return await apiFetch<T>(path);
  } catch (err) {
    if (err instanceof ApiError && err.code === "SECTION_NOT_FOUND") {
      return null;
    }
    throw err;
  }
}

export const onboardingApi = {
  // --- Legal profile (1:1) ---
  getLegalProfile: (tenantId: string) =>
    getOrNull<LegalProfileRead>(
      `/api/v1/tenants/${tenantId}/legal-profile`,
    ),
  putLegalProfile: (tenantId: string, body: LegalProfileUpsertRequest) =>
    apiFetch<LegalProfileRead>(
      `/api/v1/tenants/${tenantId}/legal-profile`,
      { method: "PUT", body: JSON.stringify(body), headers: writeHeaders() },
    ),

  // --- Tax registrations (1:N full-replace) ---
  getTaxRegistrations: (tenantId: string) =>
    apiFetch<TaxRegistrationsRead>(
      `/api/v1/tenants/${tenantId}/tax-registrations`,
    ),
  putTaxRegistrations: (
    tenantId: string,
    body: TaxRegistrationsReplaceRequest,
  ) =>
    apiFetch<TaxRegistrationsRead>(
      `/api/v1/tenants/${tenantId}/tax-registrations`,
      { method: "PUT", body: JSON.stringify(body), headers: writeHeaders() },
    ),

  // --- Billing profile (1:1) ---
  getBillingProfile: (tenantId: string) =>
    getOrNull<BillingProfileRead>(
      `/api/v1/tenants/${tenantId}/billing-profile`,
    ),
  putBillingProfile: (tenantId: string, body: BillingProfileUpsertRequest) =>
    apiFetch<BillingProfileRead>(
      `/api/v1/tenants/${tenantId}/billing-profile`,
      { method: "PUT", body: JSON.stringify(body), headers: writeHeaders() },
    ),

  // --- Contacts (1:N full-replace) ---
  getContacts: (tenantId: string) =>
    apiFetch<ContactsRead>(`/api/v1/tenants/${tenantId}/contacts`),
  putContacts: (tenantId: string, body: ContactsReplaceRequest) =>
    apiFetch<ContactsRead>(`/api/v1/tenants/${tenantId}/contacts`, {
      method: "PUT",
      body: JSON.stringify(body),
      headers: writeHeaders(),
    }),

  // --- Onboarding state (resume truth) ---
  getState: (tenantId: string) =>
    apiFetch<OnboardingStateResponse>(
      `/api/v1/tenants/${tenantId}/onboarding`,
    ),
  patchState: (tenantId: string, body: OnboardingPatchRequest) =>
    apiFetch<OnboardingStateResponse>(
      `/api/v1/tenants/${tenantId}/onboarding`,
      { method: "PATCH", body: JSON.stringify(body), headers: writeHeaders() },
    ),
};
