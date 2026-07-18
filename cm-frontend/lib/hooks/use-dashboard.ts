"use client";

import { useQuery } from "@tanstack/react-query";

import { dashboardApi } from "@/lib/api/dashboard";
import { tenantsApi } from "@/lib/api/tenants";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";

// Phase 5h.1.1 (2026-05-21): userId in queryKey to prevent cross-
// persona cache bleed. Dashboard responses are persona-shaped (KPIs
// depend on caller's RLS). See Finding #50.

export function useFleetStats() {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["dashboard-fleet-stats", userId],
    queryFn: dashboardApi.fleetStats,
    enabled: !!userId,
  });
}

export function useGovernanceStats() {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["dashboard-governance-stats", userId],
    queryFn: dashboardApi.governanceStats,
    enabled: !!userId,
  });
}

// Phase 5c.partial-deploy.hotfix2 / 5n.1: routes through tenantsApi.list
// against the real backend. Real backend supplies sort + limit
// (verified against openapi.json). Returns ListResponse<Tenant>; the
// panel consumes Tenant directly since TenantsListItem is a strict
// superset of the prior TopTenantRow shape.
export function useTopTenants() {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["top-tenants", userId],
    queryFn: () =>
      tenantsApi.list({ sort: "num_users_active_desc", limit: 10 }),
    enabled: !!userId,
  });
}
