import { disApiFetch, disQs } from "./client";
import type { ListResponse } from "@/lib/api/types";
import type { DriftEvent, DriftListParams } from "@/types/dis";

// Phase 5c.4b: read-only API surface — list + get only. Acknowledge /
// dismiss workflows defer to Phase 5d (need backend support for state
// transitions).

export const schemaDriftApi = {
  list: (params?: DriftListParams) =>
    disApiFetch<ListResponse<DriftEvent>>(
      `/api/v1/dis/schema-drift/events${disQs(params as Record<string, unknown> | undefined)}`,
    ),

  get: (id: string) =>
    disApiFetch<DriftEvent>(`/api/v1/dis/schema-drift/events/${id}`),
};
