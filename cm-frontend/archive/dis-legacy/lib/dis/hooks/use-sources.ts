"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { sourcesApi } from "@/lib/dis/api/sources";
import type {
  CreateSourceInput,
  SourceListParams,
  TestConnectionRequest,
  UpdateSourceInput,
} from "@/types/dis";

export function useSources(params?: SourceListParams) {
  return useQuery({
    queryKey: ["dis", "sources", params],
    queryFn: () => sourcesApi.list(params),
  });
}

export function useSource(id: string) {
  return useQuery({
    queryKey: ["dis", "source", id],
    queryFn: () => sourcesApi.get(id),
    enabled: !!id,
  });
}

export function useCreateSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateSourceInput) => sourcesApi.create(input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dis", "sources"] });
    },
  });
}

// No automatic invalidation — caller (StepTest) decides what to do
// with the result. Test result is transient: success → continue;
// failure → display error + retry.
export function useTestConnection() {
  return useMutation({
    mutationFn: (input: TestConnectionRequest) => sourcesApi.testConnection(input),
  });
}

// Phase 5c.2c1: edit + lifecycle mutations. Each invalidates list +
// detail caches so the UI reflects new state without manual refetch.

function useSourceMutationInvalidator(id: string) {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["dis", "sources"] });
    qc.invalidateQueries({ queryKey: ["dis", "source", id] });
  };
}

export function useUpdateSource(id: string) {
  const invalidate = useSourceMutationInvalidator(id);
  return useMutation({
    mutationFn: (input: UpdateSourceInput) => sourcesApi.update(id, input),
    onSuccess: invalidate,
  });
}

export function usePauseSource(id: string) {
  const invalidate = useSourceMutationInvalidator(id);
  return useMutation({
    mutationFn: () => sourcesApi.pause(id),
    onSuccess: invalidate,
  });
}

export function useResumeSource(id: string) {
  const invalidate = useSourceMutationInvalidator(id);
  return useMutation({
    mutationFn: () => sourcesApi.resume(id),
    onSuccess: invalidate,
  });
}

// Phase 5c.3a: also invalidates the runs list so the per-source Runs
// tab (and fleet view in 5c.3b) reflects the just-created Run record
// without a manual refetch.
export function useRunNow(id: string) {
  const qc = useQueryClient();
  const invalidate = useSourceMutationInvalidator(id);
  return useMutation({
    mutationFn: () => sourcesApi.runNow(id),
    onSuccess: () => {
      invalidate();
      qc.invalidateQueries({ queryKey: ["dis", "runs"] });
    },
  });
}

export function useRotateCredentials(id: string) {
  const invalidate = useSourceMutationInvalidator(id);
  return useMutation({
    mutationFn: () => sourcesApi.rotateCredentials(id),
    onSuccess: invalidate,
  });
}

export function useDeleteSource(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => sourcesApi.delete(id),
    onSuccess: () => {
      // Don't invalidate the source detail (it's gone). Refresh list.
      qc.invalidateQueries({ queryKey: ["dis", "sources"] });
      qc.removeQueries({ queryKey: ["dis", "source", id] });
    },
  });
}

// Phase 5c.2c2: bulk mutations. Invalidate the list query so the UI
// reflects status flips + deletions. No per-source detail invalidation
// since the list page is the consumer; if the user is also viewing a
// detail page concurrently, its TQ key remains stale until next mount —
// acceptable for bulk-from-list ergonomics.

export function useBulkPause() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sourceIds: string[]) => sourcesApi.bulkPause(sourceIds),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dis", "sources"] }),
  });
}

export function useBulkResume() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sourceIds: string[]) => sourcesApi.bulkResume(sourceIds),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dis", "sources"] }),
  });
}

export function useBulkDelete() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sourceIds: string[]) => sourcesApi.bulkDelete(sourceIds),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dis", "sources"] }),
  });
}
