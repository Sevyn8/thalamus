import { disApiFetch, disQs } from "./client";
import type { ListResponse } from "@/lib/api/types";
import type { Backfill, BackfillListParams } from "@/types/dis";

// Phase 5c.6a: read-only backfills API. Cancel + request-backfill
// flows defer to Phase 5d backend support alongside ack/resolve and
// rule mutation, mirroring the pattern across operational surfaces.

export const backfillsApi = {
  list: (params?: BackfillListParams) =>
    disApiFetch<ListResponse<Backfill>>(
      `/api/v1/dis/backfills${disQs(params as Record<string, unknown> | undefined)}`,
    ),

  get: (id: string) => disApiFetch<Backfill>(`/api/v1/dis/backfills/${id}`),
};
