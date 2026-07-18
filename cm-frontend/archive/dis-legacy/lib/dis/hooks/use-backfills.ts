"use client";

import { useQuery } from "@tanstack/react-query";

import { backfillsApi } from "@/lib/dis/api/backfills";
import type { BackfillListParams } from "@/types/dis";

export function useBackfills(params?: BackfillListParams) {
  return useQuery({
    queryKey: ["dis", "backfills", params],
    queryFn: () => backfillsApi.list(params),
  });
}

export function useBackfill(id: string) {
  return useQuery({
    queryKey: ["dis", "backfill", id],
    queryFn: () => backfillsApi.get(id),
    enabled: !!id,
  });
}
