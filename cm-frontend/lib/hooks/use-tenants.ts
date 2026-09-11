"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { tenantsApi, type TenantListParams } from "@/lib/api/tenants";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";

// `enabled` defaults to true; consumers without
// ADMIN.TENANTS.VIEW.GLOBAL pass false to skip the fetch (the endpoint
// returns 403 for TENANT JWTs; the filter dropdown they'd consume is
// also gated out for those personas).
//
// userId in queryKey prevents cross-persona cache bleed.
export function useTenants(
  params?: TenantListParams,
  options?: { enabled?: boolean },
) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["tenants", userId, params],
    queryFn: () => tenantsApi.list(params),
    enabled: (options?.enabled ?? true) && !!userId,
  });
}

export function useTenant(id: string) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["tenant", userId, id],
    queryFn: () => tenantsApi.get(id),
    enabled: !!userId && !!id,
  });
}

export function useTenantStats(options?: { enabled?: boolean }) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["tenant-stats", userId],
    queryFn: tenantsApi.stats,
    staleTime: 60_000,
    enabled: (options?.enabled ?? true) && !!userId,
  });
}

// Tenant write mutations. Server-wait pattern — no optimistic state.
// invalidateQueries is the production primitive. Invalidates list +
// detail + stats. Prefix-match means we don't need to know the active
// userId at invalidation time — ["tenants"] matches
// ["tenants", userId, ...] for every user.
//
// No audit invalidate here: the audit feed is served by
// ["audit-activities", ...] and auto-refetches on its own staleTime.

function invalidateTenant(
  queryClient: ReturnType<typeof useQueryClient>,
  id: string | undefined,
): void {
  void queryClient.invalidateQueries({ queryKey: ["tenants"] });
  void queryClient.invalidateQueries({ queryKey: ["tenant-stats"] });
  // The detail query key is ["tenant", userId, id]; a ["tenant", id]
  // key does NOT prefix-match it (id sits in the userId slot), which
  // would leave the drawer showing stale status after lifecycle
  // actions. Invalidate the ["tenant"] prefix, which matches every
  // per-user detail query. `id` is unused but kept in the signature
  // for call clarity.
  void id;
  void queryClient.invalidateQueries({ queryKey: ["tenant"] });
}

// No edit-tenant mutation here: tenant edits flow through the wizard's
// edit mode (CompanyProfileStep's CompanyEdit calls tenantsApi.patch
// directly). Lifecycle mutations below stay on the drawer.

export function useActivateTenant() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => tenantsApi.activate(id),
    onSuccess: (_data, id) => invalidateTenant(queryClient, id),
  });
}

export function useSuspendTenant() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => tenantsApi.suspend(id),
    onSuccess: (_data, id) => invalidateTenant(queryClient, id),
  });
}
