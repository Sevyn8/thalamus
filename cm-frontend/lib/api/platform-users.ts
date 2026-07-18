import { apiFetch, qs } from "./client";
import type {
  PlatformUser,
  PlatformUserListResponse,
  PlatformUserStatus,
} from "@/types/api";

export type PlatformUserListParams = {
  status?: PlatformUserStatus;
  search?: string;
  sort?: string;
  offset?: number;
  limit?: number;
};

// Phase 5n.1: routes through lib/api/client.ts, whose base URL is
// resolved at runtime via runtime-config (/api/config). Only GET
// endpoints shipped backend-side; writes (5h) pending.
export const platformUsersApi = {
  list: (params?: PlatformUserListParams) =>
    apiFetch<PlatformUserListResponse>(
      `/api/v1/platform-users${qs(params as Record<string, unknown> | undefined)}`,
    ),
  get: (id: string) =>
    apiFetch<PlatformUser>(`/api/v1/platform-users/${id}`),
};
