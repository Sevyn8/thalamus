"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  tenantsApi,
  type TenantListParams,
  type TenantPatchPayload,
} from "@/lib/api/tenants";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";

// Phase 5g.1: `enabled` defaults to true; consumers without
// ADMIN.TENANTS.VIEW.GLOBAL pass false to skip the fetch (the endpoint
// returns 403 for TENANT JWTs; the filter dropdown they'd consume is
// also gated out for those personas).
//
// Phase 5h.1.1 (2026-05-21): userId in queryKey to prevent cross-
// persona cache bleed. See Finding #50.
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

// Phase 5n.5: tenant write mutations. Server-wait pattern — no
// optimistic state. invalidateQueries is the production primitive.
// Invalidates list + detail + stats. Prefix-match means we don't
// need to know the active userId at invalidation time —
// ["tenants"] matches ["tenants", userId, ...] for every user.
//
// Phase 5h.4: dropped the ["audit-logs"] invalidate — that hook
// was deleted in the audit-logs cleanup. The audit feed is served
// by ["audit-activities", ...] now and auto-refetches on its own
// staleTime; tenant writes don't need to explicitly invalidate it.

function invalidateTenant(
  queryClient: ReturnType<typeof useQueryClient>,
  id: string | undefined,
): void {
  void queryClient.invalidateQueries({ queryKey: ["tenants"] });
  void queryClient.invalidateQueries({ queryKey: ["tenant-stats"] });
  if (id) {
    void queryClient.invalidateQueries({ queryKey: ["tenant", id] });
  }
}

export function useEditTenant() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: TenantPatchPayload }) =>
      tenantsApi.patch(id, patch),
    onSuccess: (_data, { id }) => invalidateTenant(queryClient, id),
  });
}

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
