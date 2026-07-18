"use client";

import { useQuery } from "@tanstack/react-query";

import { changelogApi } from "@/lib/dis/api/changelog";

// Phase 5c.8f2: changelog read-only hook.

export function useChangelog() {
  return useQuery({
    queryKey: ["dis", "changelog"],
    queryFn: () => changelogApi.read(),
  });
}
