import { apiFetch, qs } from "./client";
import type { ListResponse } from "./types";
import type { Notification } from "@/types/api";

export type NotificationListParams = {
  read?: boolean;
  limit?: number;
  offset?: number;
};

// Phase 5n.1: routes through lib/api/client.ts, whose base URL is
// resolved at runtime via runtime-config (/api/config).
// Sanjeev's backend has no /notifications endpoint yet — consumers
// will see empty/404 responses until that ships. See BUILD_PLAN
// Finding #31.
export const notificationsApi = {
  list: (params?: NotificationListParams) =>
    apiFetch<ListResponse<Notification>>(
      `/api/v1/notifications${qs(params as Record<string, unknown> | undefined)}`,
    ),
};
