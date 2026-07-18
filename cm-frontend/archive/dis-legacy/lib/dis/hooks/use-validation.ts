"use client";

import { useQuery } from "@tanstack/react-query";

import { validationApi } from "@/lib/dis/api/validation";
import type { ValidationListParams } from "@/types/dis";

// Phase 5c.4a: simple useQuery for list/get + per-rule violations.
// No infinite scroll in v1 — most fleets have <100 rules; pagination
// lands if real-backend numbers warrant it.

export function useValidationRules(params?: ValidationListParams) {
  return useQuery({
    queryKey: ["dis", "validation", "rules", params],
    queryFn: () => validationApi.list(params),
  });
}

export function useValidationRule(id: string) {
  return useQuery({
    queryKey: ["dis", "validation", "rule", id],
    queryFn: () => validationApi.get(id),
    enabled: !!id,
  });
}

export function useValidationViolations(ruleId: string) {
  return useQuery({
    queryKey: ["dis", "validation", "violations", ruleId],
    queryFn: () => validationApi.getViolations(ruleId),
    enabled: !!ruleId,
  });
}
