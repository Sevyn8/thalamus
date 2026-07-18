"use client";

import { useQuery } from "@tanstack/react-query";

import { llmOpsApi } from "@/lib/dis/api/llm-ops";
import type { LlmOpsTimeWindow } from "@/types/dis";

// Phase 5c.8c: LLM ops admin reads. Window-scoped query keys so
// switching windows doesn't share cache; React Query refetches per
// window naturally.

export function useLlmOpsFleet(window: LlmOpsTimeWindow) {
  return useQuery({
    queryKey: ["dis", "admin", "llm-ops", "fleet", window],
    queryFn: () => llmOpsApi.fleet(window),
  });
}

export function useLlmOpsTenant(tenantId: string, window: LlmOpsTimeWindow) {
  return useQuery({
    queryKey: ["dis", "admin", "llm-ops", "tenant", tenantId, window],
    queryFn: () => llmOpsApi.tenant(tenantId, window),
    enabled: tenantId.length > 0,
  });
}
