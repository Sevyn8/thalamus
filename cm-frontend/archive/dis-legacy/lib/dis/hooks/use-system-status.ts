"use client";

import { useQuery } from "@tanstack/react-query";

import { systemStatusApi } from "@/lib/dis/api/system-status";

// Phase 5c.8f2: system status snapshot read-only hook. Single
// shape; no params. Matches the docs / changelog informational-
// surface trio.

export function useSystemStatus() {
  return useQuery({
    queryKey: ["dis", "system-status"],
    queryFn: () => systemStatusApi.read(),
  });
}
