"use client";

import { useQuery } from "@tanstack/react-query";

import { notificationsApi, type NotificationListParams } from "@/lib/api/notifications";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";

// Phase 5h.1.1 (2026-05-21): userId in queryKey to prevent cross-
// persona cache bleed. See Finding #50.
export function useNotifications(params?: NotificationListParams) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["notifications", userId, params],
    queryFn: () => notificationsApi.list(params),
    staleTime: 30_000,
    enabled: !!userId,
  });
}
