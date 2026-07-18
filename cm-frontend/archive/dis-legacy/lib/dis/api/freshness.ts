import { disApiFetch, disQs } from "./client";
import type { ListResponse } from "@/lib/api/types";
import type { Freshness, FreshnessListParams } from "@/types/dis";

// Phase 5c.4c: read-only API surface. State-transition workflows
// (acknowledge / resolve) defer to Phase 5d backend support, mirroring
// the drift-events pattern.

export const freshnessApi = {
  list: (params?: FreshnessListParams) =>
    disApiFetch<ListResponse<Freshness>>(
      `/api/v1/dis/freshness${disQs(params as Record<string, unknown> | undefined)}`,
    ),

  getBySource: (sourceId: string) =>
    disApiFetch<Freshness>(`/api/v1/dis/freshness/sources/${sourceId}`),
};
