import { disApiFetch, disQs } from "./client";
import type { ListResponse } from "@/lib/api/types";
import type {
  BulkActionResponse,
  CreateSourceInput,
  Run,
  Source,
  SourceDetail,
  SourceListParams,
  TestConnectionRequest,
  TestConnectionResult,
  UpdateSourceInput,
} from "@/types/dis";

// Phase 5c.2a: read-only API surface — list + get only.
//
// Mutation methods (`create`, `update`, `delete`, `pause`, `resume`,
// `runNow`, `rotateCredentials`, `testConnection`) land in 5c.2b/5c.2c
// alongside their consumer surfaces (wizard / edit form / lifecycle
// actions). Declaring them here as throwing stubs would let consumers
// import them now, but consumers don't exist in 5c.2a — keeping the
// API minimal until a real call site arrives.

export const sourcesApi = {
  list: (params?: SourceListParams) =>
    disApiFetch<ListResponse<Source>>(
      `/api/v1/dis/sources${disQs(params as Record<string, unknown> | undefined)}`,
    ),

  get: (id: string) => disApiFetch<SourceDetail>(`/api/v1/dis/sources/${id}`),

  // Idempotency-Key per call, matching the Ithina pattern. Returns the
  // full created source so the wizard can route directly to /dis/sources/[id]
  // without a follow-up GET.
  create: (input: CreateSourceInput) =>
    disApiFetch<Source>(`/api/v1/dis/sources`, {
      method: "POST",
      body: JSON.stringify(input),
      headers: {
        "Idempotency-Key": crypto.randomUUID(),
      },
    }),

  testConnection: (input: TestConnectionRequest) =>
    disApiFetch<TestConnectionResult>(`/api/v1/dis/sources/test-connection`, {
      method: "POST",
      body: JSON.stringify(input),
    }),

  // Phase 5c.2c1: PATCH update. Returns the full updated source.
  update: (id: string, input: UpdateSourceInput) =>
    disApiFetch<Source>(`/api/v1/dis/sources/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),

  // Lifecycle actions. Each idempotency-keyed; each returns the
  // updated source so the cache reflects the new status without a
  // follow-up GET.
  pause: (id: string) =>
    disApiFetch<Source>(`/api/v1/dis/sources/${id}/pause`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),

  resume: (id: string) =>
    disApiFetch<Source>(`/api/v1/dis/sources/${id}/resume`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),

  // Phase 5c.3a: returns the created Run (was Source in 5c.2c1). Source
  // state updates server-side too — caller invalidates ["dis", "source"]
  // queries to pick up the new last_run_at.
  runNow: (id: string) =>
    disApiFetch<Run>(`/api/v1/dis/sources/${id}/run-now`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),

  rotateCredentials: (id: string) =>
    disApiFetch<Source>(`/api/v1/dis/sources/${id}/rotate-credentials`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),

  delete: (id: string) =>
    disApiFetch<void>(`/api/v1/dis/sources/${id}`, {
      method: "DELETE",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),

  // Phase 5c.2c2: bulk actions. 3 separate endpoints; each accepts
  // { source_ids } and returns per-source results. Real backend can
  // align to this shape or switch to a single /bulk endpoint with a
  // discriminated action; v1 contract is forward-compatible either way.
  bulkPause: (sourceIds: string[]) =>
    disApiFetch<BulkActionResponse>(`/api/v1/dis/sources/bulk-pause`, {
      method: "POST",
      body: JSON.stringify({ source_ids: sourceIds }),
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),

  bulkResume: (sourceIds: string[]) =>
    disApiFetch<BulkActionResponse>(`/api/v1/dis/sources/bulk-resume`, {
      method: "POST",
      body: JSON.stringify({ source_ids: sourceIds }),
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),

  bulkDelete: (sourceIds: string[]) =>
    disApiFetch<BulkActionResponse>(`/api/v1/dis/sources/bulk-delete`, {
      method: "POST",
      body: JSON.stringify({ source_ids: sourceIds }),
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),
};
