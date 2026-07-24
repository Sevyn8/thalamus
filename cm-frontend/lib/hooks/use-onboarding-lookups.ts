"use client";

import { useQuery } from "@tanstack/react-query";

import { lookupsApi, type LookupMap } from "@/lib/api/lookups";

// The six coded lists the onboarding wizard's selects need. Fetched from
// the lookups endpoint via the additive `lists()` path (not the fixed
// 4-list `all()`), so nothing is hardcoded. One request, cached an hour
// (lookups are reference data), shared across all wizard steps.
export const ONBOARDING_LOOKUP_LISTS = [
  "entity_type",
  "tax_registration_type",
  "payment_terms",
  "currency",
  "contact_type",
  "document_type",
] as const;

export function useOnboardingLookups() {
  return useQuery<LookupMap>({
    queryKey: ["lookups", "onboarding", ...ONBOARDING_LOOKUP_LISTS],
    queryFn: () => lookupsApi.lists(ONBOARDING_LOOKUP_LISTS),
    staleTime: 60 * 60_000,
  });
}
