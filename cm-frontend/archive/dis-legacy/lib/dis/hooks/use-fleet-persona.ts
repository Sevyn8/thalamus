"use client";

import { useAuthSnapshot } from "@/lib/auth/auth-cache";

// Phase 5c.4d-prep: persona-scoping policy for DIS operational
// fleet pages (runs / validation / drift / freshness; later
// alerts events / rules). Centralized so the policy lives in one
// place — when Phase 5d cutover lands and RLS moves server-side,
// this hook is the single update point.
//
// Policy:
//   - PLATFORM (Anjali): no auto-scope. Tenant dropdown drives the
//     filter — empty value means "All tenants" (no tenant_id sent).
//   - TENANT (Kowalski): auto-locked to persona.tenantId. Dropdown
//     is hidden by the consuming page (showTenantFilter prop on
//     each surface's Filters component).
//
// `resolveTenantId(dropdownValue)` collapses both branches to a
// single string-or-undefined call site so consumer pages don't
// re-implement the if/else.

export function useFleetPersona() {
  const snapshot = useAuthSnapshot();
  const isPlatform = snapshot?.user.userType === "PLATFORM";
  const personaTenantId = snapshot?.user.tenantId ?? null;

  function resolveTenantId(dropdownValue: string): string | undefined {
    if (isPlatform) return dropdownValue || undefined;
    return personaTenantId ?? undefined;
  }

  return { isPlatform, personaTenantId, resolveTenantId };
}
