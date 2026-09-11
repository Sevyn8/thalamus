"use client";

import { useQuery } from "@tanstack/react-query";

import { dashboardApi } from "@/lib/api/dashboard";
import { tenantsApi } from "@/lib/api/tenants";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";

// userId in queryKey prevents cross-persona cache bleed. Dashboard
// responses are persona-shaped (KPIs depend on caller's RLS).

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

// Routes through tenantsApi.list; the backend supplies sort + limit.
// Returns ListResponse<Tenant>, which the panel consumes directly.
export function useTopTenants() {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["top-tenants", userId],
    queryFn: () =>
      tenantsApi.list({ sort: "num_users_active_desc", limit: 10 }),
    enabled: !!userId,
  });
}
