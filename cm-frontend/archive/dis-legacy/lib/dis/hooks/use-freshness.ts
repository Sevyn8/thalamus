"use client";

import { useQuery } from "@tanstack/react-query";

import { freshnessApi } from "@/lib/dis/api/freshness";
import type { FreshnessListParams } from "@/types/dis";

export function useFreshnessList(params?: FreshnessListParams) {
  return useQuery({
    queryKey: ["dis", "freshness", params],
    queryFn: () => freshnessApi.list(params),
  });
}

// Keyed by source_id (v1 1:1 mapping). When real backend introduces
// multi-SLO-per-source, a sibling useFreshness(freshnessId) hook
// can land alongside without breaking this one.
export function useFreshnessForSource(sourceId: string) {
  return useQuery({
    queryKey: ["dis", "freshness", "source", sourceId],
    queryFn: () => freshnessApi.getBySource(sourceId),
    enabled: !!sourceId,
  });
}

// Phase 5e.4b: per-stream freshness fetch. Uses the list endpoint with
// stream_id filter (server returns 0 or 1 row in v1). Distinct from
// useFreshnessForSource because multi-SLO-per-source is now real —
// asking by source returns the first matching record, asking by stream
// returns the one belonging to that specific feed.
export function useFreshnessForStream(streamId: string) {
  return useQuery({
    queryKey: ["dis", "freshness", "stream", streamId],
    queryFn: async () => {
      const res = await freshnessApi.list({ stream_id: streamId, limit: 1 });
      return res.items[0] ?? null;
    },
    enabled: !!streamId,
  });
}
