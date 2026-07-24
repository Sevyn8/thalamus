"use client";

import { useQuery } from "@tanstack/react-query";

import { resolveTenantModuleRow } from "@/lib/api/modules";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";

// Resolves the single tenant's module row from the fleet matrix,
// deterministically by tenant_id (see resolveTenantModuleRow). Separate
// query key from the fleet ["module-access-matrix"] so the wizard's
// per-tenant view is cached independently; the toggle handler invalidates
// this key explicitly after a write.
export function useTenantModuleRow(tenantId: string, tenantName?: string) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["tenant-module-row", userId, tenantId],
    queryFn: () => resolveTenantModuleRow(tenantId, tenantName),
    enabled: !!userId && !!tenantId,
    staleTime: 60_000,
  });
}

export const TENANT_MODULE_ROW_KEY = ["tenant-module-row"] as const;
