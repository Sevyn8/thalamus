import { disApiFetch, disQs } from "./client";
import type { ListResponse } from "@/lib/api/types";
import type {
  CreateStreamInput,
  Run,
  Stream,
  StreamListParams,
  UpdateStreamInput,
} from "@/types/dis";

// Phase 5e.4a: read + Phase 5e.4d: mutations. Mirrors sourcesApi
// shape — same Idempotency-Key pattern (UUID per call at request time
// per PATTERNS.md guidance, not at hook instantiation).

export const streamsApi = {
  list: (params?: StreamListParams) =>
    disApiFetch<ListResponse<Stream>>(
      `/api/v1/dis/streams${disQs(params as Record<string, unknown> | undefined)}`,
    ),

  get: (id: string) => disApiFetch<Stream>(`/api/v1/dis/streams/${id}`),

  create: (input: CreateStreamInput) =>
    disApiFetch<Stream>(`/api/v1/dis/streams`, {
      method: "POST",
      body: JSON.stringify(input),
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),

  update: (id: string, input: UpdateStreamInput) =>
    disApiFetch<Stream>(`/api/v1/dis/streams/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),

  pause: (id: string) =>
    disApiFetch<Stream>(`/api/v1/dis/streams/${id}/pause`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),

  resume: (id: string) =>
    disApiFetch<Stream>(`/api/v1/dis/streams/${id}/resume`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),

  // Mirrors sourcesApi.runNow: returns the created Run so the caller
  // can show its synthesized state (status, started_at) in a toast
  // without a follow-up GET. The runs list query invalidates on
  // success so the Stream detail page's Runs tab picks it up.
  runNow: (id: string) =>
    disApiFetch<Run>(`/api/v1/dis/streams/${id}/run-now`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),
};
