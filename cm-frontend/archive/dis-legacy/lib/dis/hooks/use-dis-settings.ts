"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { disSettingsApi } from "@/lib/dis/api/dis-settings";
import type { UpdateDisSettingsInput } from "@/types/dis";

export function useDisSettings() {
  return useQuery({
    queryKey: ["dis", "settings"],
    queryFn: () => disSettingsApi.get(),
    // Settings are session-relevant; brief staleTime so toggle changes
    // reflect quickly without spamming the network.
    staleTime: 10_000,
  });
}

export function useUpdateDisSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: UpdateDisSettingsInput) => disSettingsApi.update(input),
    onSuccess: (data) => {
      qc.setQueryData(["dis", "settings"], data);
      // Per Phase 5c.1c A5: settings change invalidates open upload
      // queries so MappingReviewView refetches with the new effective
      // LLM-assist state immediately rather than on next page load.
      qc.invalidateQueries({ queryKey: ["dis", "upload"] });
    },
  });
}
