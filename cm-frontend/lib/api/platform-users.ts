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

// Routes through lib/api/client.ts, whose base URL is resolved at
// runtime via runtime-config (/api/config). Read-only: the backend
// exposes only GET endpoints for platform users.
export const platformUsersApi = {
  list: (params?: PlatformUserListParams) =>
    apiFetch<PlatformUserListResponse>(
      `/api/v1/platform-users${qs(params as Record<string, unknown> | undefined)}`,
    ),
  get: (id: string) =>
    apiFetch<PlatformUser>(`/api/v1/platform-users/${id}`),
};
