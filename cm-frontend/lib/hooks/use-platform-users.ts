"use client";

import { useQuery } from "@tanstack/react-query";

import {
  platformUsersApi,
  type PlatformUserListParams,
} from "@/lib/api/platform-users";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";

// `enabled` defaults to true; callers without
// ADMIN.USERS.VIEW.GLOBAL pass false to skip the fetch (avoids a noisy
// 403 in the Network tab for TENANT-OWNER personas who can never see
// the Platform tab).
//
// userId in queryKey prevents cross-persona cache bleed.
export function usePlatformUsers(
  params?: PlatformUserListParams,
  options?: { enabled?: boolean },
) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["platform-users", userId, params],
    queryFn: () => platformUsersApi.list(params),
    enabled: (options?.enabled ?? true) && !!userId,
  });
}

export function usePlatformUser(id: string) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["platform-user", userId, id],
    queryFn: () => platformUsersApi.get(id),
    enabled: !!userId && !!id,
  });
}
