"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { runsApi } from "@/lib/dis/api/runs";
import type { RunListParams } from "@/types/dis";

// Phase 5c.3a: useRuns is a simple useQuery for the per-source Runs
// tab (most sources have <10 runs; pagination not needed).
//
// Phase 5c.3b: useInfiniteRuns added for the fleet /dis/runs page —
// offset-based pagination at 25/page, with getNextPageParam computed
// from the running total vs. the response's pagination.total.
export function useRuns(params?: RunListParams, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ["dis", "runs", params],
    queryFn: () => runsApi.list(params),
    enabled: options?.enabled ?? true,
  });
}

export function useInfiniteRuns(params?: Omit<RunListParams, "offset">) {
  const limit = params?.limit ?? 25;
  return useInfiniteQuery({
    queryKey: ["dis", "runs", "infinite", params],
    queryFn: ({ pageParam }) =>
      runsApi.list({ ...params, offset: pageParam, limit }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      const totalLoaded = allPages.reduce((acc, p) => acc + p.items.length, 0);
      return totalLoaded < lastPage.pagination.total ? totalLoaded : undefined;
    },
  });
}

export function useRun(id: string) {
  return useQuery({
    queryKey: ["dis", "run", id],
    queryFn: () => runsApi.get(id),
    enabled: !!id,
  });
}
