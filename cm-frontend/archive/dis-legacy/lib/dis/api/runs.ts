import { disApiFetch, disQs } from "./client";
import type { ListResponse } from "@/lib/api/types";
import type { Run, RunListParams } from "@/types/dis";

// Phase 5c.3a: read-only API surface — list + get only.
//
// Run-creation flow stays on the source-scoped endpoint (POST
// /api/v1/dis/sources/:id/run-now) per real backend convention; that
// endpoint now returns the created Run (instead of the updated Source
// it returned in 5c.2c1). See lib/dis/api/sources.ts#runNow.
//
// Future surfaces (Phase 5c.3b fleet page, 5d streaming logs):
//   - useInfiniteRuns wrapper for fleet pagination
//   - GET /runs/:id/logs (5d)
//   - POST /runs/:id/cancel (5d, alongside RUNNING-state cancellation)

export const runsApi = {
  list: (params?: RunListParams) =>
    disApiFetch<ListResponse<Run>>(
      `/api/v1/dis/runs${disQs(params as Record<string, unknown> | undefined)}`,
    ),

  get: (id: string) => disApiFetch<Run>(`/api/v1/dis/runs/${id}`),
};
