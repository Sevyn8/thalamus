"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { costApi } from "@/lib/dis/api/cost";
import type { SetBudgetInput } from "@/types/dis";

// Phase 5c.8e2: Cost fleet read + budget mutation. Mutation
// invalidates the fleet query so the row's chip + values update
// after Save.

export function useCostFleet() {
  return useQuery({
    queryKey: ["dis", "admin", "cost", "fleet"],
    queryFn: () => costApi.fleet(),
  });
}

export function useSetBudget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { tenantId: string; input: SetBudgetInput }) =>
      costApi.setBudget(args.tenantId, args.input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["dis", "admin", "cost"] });
    },
  });
}
