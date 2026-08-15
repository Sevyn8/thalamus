"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  modulesApi,
  type ModuleMatrixParams,
  type WritableModuleCode,
} from "@/lib/api/modules";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";

// Phase 5h.1.1 (2026-05-21): userId in queryKey to prevent cross-
// persona cache bleed. See Finding #50.

export function useModuleCards() {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["module-access-cards", userId],
    queryFn: modulesApi.cards,
    staleTime: 5 * 60_000,
    enabled: !!userId,
  });
}

export function useModuleMatrix(params?: ModuleMatrixParams) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["module-access-matrix", userId, params],
    queryFn: () => modulesApi.matrix(params),
    // Phase 5d.1: matrix is slow-changing data. 5-min staleTime
    // matches useModuleCards; benefits the My Sevyn8 launcher
    // (TENANT path reads matrix on every visit) and the existing
    // /superadmin/modules consumer alike.
    staleTime: 5 * 60_000,
    enabled: !!userId,
  });
}

// Slice 8: the caller's OWN tenant's enabled modules. Powers the
// tenant-persona launcher via the GATE_EXEMPT /module-access/me read
// (the matrix endpoint is admin-gated and 403s for tenant users). Only
// enable it for TENANT personas; PLATFORM tiles are static and need no
// fetch. userId in the queryKey per the cross-persona cache-bleed rule.
export function useMyModules(options?: { enabled?: boolean }) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["module-access-me", userId],
    queryFn: modulesApi.myModules,
    staleTime: 5 * 60_000,
    enabled: (options?.enabled ?? true) && !!userId,
  });
}

// Phase 5j: write cutover. Server-wait UX (no optimistic state) per
// Architectural Finding #28; the matrix cell toggle is a single binary
// flip with a short server roundtrip, optimistic state is not justified.
// onSuccess invalidates the read queries so the matrix re-renders with
// the persisted status. invalidateQueries (NOT refetchQueries) is the
// canonical production-code primitive; refetch is test-infra-only
// (Finding #25).

type ToggleInput = { tenantId: string; moduleCode: WritableModuleCode };

export function useEnableModuleAccess() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ tenantId, moduleCode }: ToggleInput) =>
      modulesApi.enable(tenantId, moduleCode),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["module-access-matrix"] });
      void queryClient.invalidateQueries({ queryKey: ["module-access-cards"] });
    },
  });
}

export function useDisableModuleAccess() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ tenantId, moduleCode }: ToggleInput) =>
      modulesApi.disable(tenantId, moduleCode),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["module-access-matrix"] });
      void queryClient.invalidateQueries({ queryKey: ["module-access-cards"] });
    },
  });
}
