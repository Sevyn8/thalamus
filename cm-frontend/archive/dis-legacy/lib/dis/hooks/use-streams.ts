"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { streamsApi } from "@/lib/dis/api/streams";
import type {
  CreateStreamInput,
  StreamListParams,
  UpdateStreamInput,
} from "@/types/dis";

export function useStreams(params?: StreamListParams) {
  return useQuery({
    queryKey: ["dis", "streams", params],
    queryFn: () => streamsApi.list(params),
  });
}

export function useStream(id: string) {
  return useQuery({
    queryKey: ["dis", "stream", id],
    queryFn: () => streamsApi.get(id),
    enabled: !!id,
  });
}

// Phase 5e.4d: mutations. Pattern mirrors use-sources.ts —
// invalidations cover both list and detail queries, plus the
// dependent run-list query for runNow.

export function useCreateStream() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateStreamInput) => streamsApi.create(input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dis", "streams"] });
      // Parent source's stream_count denorm changes too.
      qc.invalidateQueries({ queryKey: ["dis", "sources"] });
    },
  });
}

function useStreamMutationInvalidator(id: string) {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["dis", "streams"] });
    qc.invalidateQueries({ queryKey: ["dis", "stream", id] });
  };
}

export function useUpdateStream(id: string) {
  const invalidate = useStreamMutationInvalidator(id);
  return useMutation({
    mutationFn: (input: UpdateStreamInput) => streamsApi.update(id, input),
    onSuccess: invalidate,
  });
}

export function usePauseStream(id: string) {
  const invalidate = useStreamMutationInvalidator(id);
  return useMutation({
    mutationFn: () => streamsApi.pause(id),
    onSuccess: invalidate,
  });
}

export function useResumeStream(id: string) {
  const invalidate = useStreamMutationInvalidator(id);
  return useMutation({
    mutationFn: () => streamsApi.resume(id),
    onSuccess: invalidate,
  });
}

// Mirrors useRunNow on sources. Invalidates the runs list so the
// stream detail page's Runs tab picks up the new row, plus the
// stream's last_run_at via stream detail invalidation.
export function useRunStreamNow(id: string) {
  const qc = useQueryClient();
  const invalidate = useStreamMutationInvalidator(id);
  return useMutation({
    mutationFn: () => streamsApi.runNow(id),
    onSuccess: () => {
      invalidate();
      qc.invalidateQueries({ queryKey: ["dis", "runs"] });
    },
  });
}
