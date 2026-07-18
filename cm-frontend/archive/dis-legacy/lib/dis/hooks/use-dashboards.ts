"use client";

import { useQuery } from "@tanstack/react-query";

import { dashboardsApi } from "@/lib/dis/api/dashboards";

// Phase 5e.10b: dashboard query. Tenant-scoped query key so
// switching tenants triggers a fresh fetch naturally.

export function useDashboard(tenantId: string) {
  return useQuery({
    queryKey: ["dis", "dashboards", tenantId],
    queryFn: () => dashboardsApi.tenant(tenantId),
    enabled: tenantId.length > 0,
  });
}
