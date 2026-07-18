import { disApiFetch } from "./client";
import type { ChangelogResponse } from "@/types/dis";

// Phase 5c.8f2: read-only changelog. Single endpoint; static
// fixture server-side. No query params.

export const changelogApi = {
  read: () => disApiFetch<ChangelogResponse>(`/api/v1/dis/changelog`),
};
