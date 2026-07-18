"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  rolesApi,
  type PermissionListParams,
  type RoleAssignmentsParams,
  type RoleListParams,
  type RoleUpdateRequest,
} from "@/lib/api/roles";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";

// Phase 5h.1.1 (2026-05-21): userId in queryKey to prevent cross-
// persona cache bleed. See Finding #50.

export function useRoles(params?: RoleListParams) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["roles", userId, params],
    queryFn: () => rolesApi.list(params),
    enabled: !!userId,
  });
}

export function useRolePermissions(roleId: string) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["role-permissions", userId, roleId],
    queryFn: () => rolesApi.getPermissions(roleId),
    enabled: !!userId && !!roleId,
  });
}

export function usePermissions(params?: PermissionListParams) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["permissions", userId, params],
    queryFn: () => rolesApi.permissions(params),
    staleTime: 5 * 60_000,
    enabled: !!userId,
  });
}

export function usePermissionMatrix() {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["permission-matrix", userId],
    queryFn: rolesApi.matrix,
    staleTime: 5 * 60_000,
    enabled: !!userId,
  });
}

// Phase 5d.3: role-assignments. Server-side RLS scopes for TENANT
// JWTs; client passes filters through unchanged.
export function useRoleAssignments(params?: RoleAssignmentsParams) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["role-assignments", userId, params],
    queryFn: () => rolesApi.assignments(params),
    enabled: !!userId,
  });
}

// Phase 5n.10: role detail (Step 6.18.2) + update (Step 6.18.3).
// Detail query keyed by id so multiple edit modals don't share state;
// invalidated alongside the role list + permission matrix on update.

export function useRoleDetail(roleId: string) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["role", userId, roleId],
    queryFn: () => rolesApi.detail(roleId),
    enabled: !!userId && !!roleId,
  });
}

export function useUpdateRole() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: RoleUpdateRequest }) =>
      rolesApi.update(id, patch),
    onSuccess: (_data, { id }) => {
      void queryClient.invalidateQueries({ queryKey: ["roles"] });
      void queryClient.invalidateQueries({ queryKey: ["role", id] });
      void queryClient.invalidateQueries({ queryKey: ["role-permissions", id] });
      void queryClient.invalidateQueries({ queryKey: ["permission-matrix"] });
    },
  });
}
