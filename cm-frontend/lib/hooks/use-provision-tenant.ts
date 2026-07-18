"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { tenantsApi } from "@/lib/api/tenants";
import type { ProvisionTenantInput } from "@/lib/schemas/provision-tenant";
import type { Tenant } from "@/types/api";

// Phase 5n.5 (2026-05-18): optimistic CREATE retired. Server-wait UX
// matches the canonical post-MSW pattern (Phase 5-stores Finding #32).
// The synthesized temp_uuid row was a UX-latency-masking concession
// in 5c-era that broke down once the real backend roundtrip became
// deterministic; backend-truth principle says the list row appears
// only after the POST resolves and the invalidate-triggered refetch
// lands. Auto-navigate-to-drawer-after-create also removed (lived in
// ProvisionTenantModal): it cascaded into the tenant-detail 404 bug
// (Sanjeev queue) for post-seed tenants.

export function useProvisionTenant() {
  const queryClient = useQueryClient();

  return useMutation<Tenant, Error, ProvisionTenantInput>({
    mutationFn: (input) => tenantsApi.provision(input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["tenants"] });
      void queryClient.invalidateQueries({ queryKey: ["tenant-stats"] });
    },
  });
}
