"use client";

import { useQuery } from "@tanstack/react-query";

import { notificationsApi, type NotificationListParams } from "@/lib/api/notifications";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";

// userId in queryKey prevents cross-persona cache bleed.
// There is no /api/v1/notifications backend route, so an enabled
// poll would 404 on every page. Disabled until a notifications backend ships
// (do not build one here). The bell still renders its empty state; flip
// `enabled` back to `!!userId` when the endpoint exists.
const NOTIFICATIONS_BACKEND_AVAILABLE = false;

export function useNotifications(params?: NotificationListParams) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["notifications", userId, params],
    queryFn: () => notificationsApi.list(params),
    staleTime: 30_000,
    enabled: NOTIFICATIONS_BACKEND_AVAILABLE && !!userId,
  });
}
