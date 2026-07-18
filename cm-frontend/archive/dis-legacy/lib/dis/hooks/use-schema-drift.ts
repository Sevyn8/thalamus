"use client";

import { useQuery } from "@tanstack/react-query";

import { schemaDriftApi } from "@/lib/dis/api/schema-drift";
import type { DriftListParams } from "@/types/dis";

// Phase 5c.4b: simple useQuery for list/get. No infinite scroll for
// v1 — drift events are infrequent by nature; pagination if real-
// backend numbers warrant it.

export function useDriftEvents(params?: DriftListParams) {
  return useQuery({
    queryKey: ["dis", "schema-drift", params],
    queryFn: () => schemaDriftApi.list(params),
  });
}

export function useDriftEvent(id: string) {
  return useQuery({
    queryKey: ["dis", "schema-drift", "event", id],
    queryFn: () => schemaDriftApi.get(id),
    enabled: !!id,
  });
}
