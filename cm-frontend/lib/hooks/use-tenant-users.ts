"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  tenantUsersApi,
  type TenantUserCreatePayload,
  type TenantUserListParams,
  type TenantUserPatchPayload,
} from "@/lib/api/tenant-users";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";

// userId in queryKey prevents cross-persona cache bleed.

export function useTenantUsers(params?: TenantUserListParams) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["tenant-users", userId, params],
    queryFn: () => tenantUsersApi.list(params),
    enabled: !!userId,
  });
}

export function useTenantUser(id: string) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["tenant-user", userId, id],
    queryFn: () => tenantUsersApi.get(id),
    enabled: !!userId && !!id,
  });
}

// Write hooks. Server-wait pattern — no optimistic state. Both list +
// per-user caches are invalidated on success — list because status / roles
// affect row rendering; detail because the drawer reads from it.

function invalidateTenantUser(
  queryClient: ReturnType<typeof useQueryClient>,
  id: string | undefined,
): void {
  void queryClient.invalidateQueries({ queryKey: ["tenant-users"] });
  if (id) {
    void queryClient.invalidateQueries({ queryKey: ["tenant-user", id] });
  }
}

export function useCreateTenantUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: TenantUserCreatePayload) => tenantUsersApi.create(input),
    onSuccess: (data) => invalidateTenantUser(queryClient, data.id),
  });
}

export function useEditTenantUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: TenantUserPatchPayload }) =>
      tenantUsersApi.patch(id, patch),
    onSuccess: (_data, { id }) => invalidateTenantUser(queryClient, id),
  });
}

export function useActivateTenantUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => tenantUsersApi.activate(id),
    onSuccess: (_data, id) => invalidateTenantUser(queryClient, id),
  });
}

export function useSuspendTenantUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => tenantUsersApi.suspend(id),
    onSuccess: (_data, id) => invalidateTenantUser(queryClient, id),
  });
}
