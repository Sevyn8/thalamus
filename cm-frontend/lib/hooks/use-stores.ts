"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  storesApi,
  type StoreCreatePayload,
  type StoreListParams,
  type StorePatchPayload,
} from "@/lib/api/stores";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import type { StoreStatus } from "@/types/api";

// Stores react-query hooks. Server-wait pattern (no optimistic
// state). invalidateQueries on success — the production-canonical
// primitive.
//
// userId in queryKey prevents cross-persona cache bleed.

export function useStores(params?: StoreListParams) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["stores", userId, params],
    queryFn: () => storesApi.list(params),
    enabled: !!userId,
  });
}

export function useStore(id: string) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["store", userId, id],
    queryFn: () => storesApi.get(id),
    enabled: !!userId && !!id,
  });
}

function invalidateStore(
  queryClient: ReturnType<typeof useQueryClient>,
  id: string | undefined,
): void {
  void queryClient.invalidateQueries({ queryKey: ["stores"] });
  if (id) {
    void queryClient.invalidateQueries({ queryKey: ["store", id] });
  }
}

export function useCreateStore() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: StoreCreatePayload) => storesApi.create(input),
    onSuccess: (data) => invalidateStore(queryClient, data.id),
  });
}

export function useUpdateStore() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: StorePatchPayload }) =>
      storesApi.patch(id, patch),
    onSuccess: (_data, { id }) => invalidateStore(queryClient, id),
  });
}

export function useSetStoreStatus() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      target_status,
      reason,
    }: {
      id: string;
      target_status: StoreStatus;
      reason?: string;
    }) => storesApi.setStatus(id, target_status, reason),
    onSuccess: (_data, { id }) => invalidateStore(queryClient, id),
  });
}
