"use client";

import { useQuery } from "@tanstack/react-query";

import { auditApi, type AuditListParams } from "@/lib/api/audit";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";

// Phase 5h.1 (2026-05-21): audit activities feed. Server-wait, no
// optimistic state. Audit rows are append-only — `staleTime` of 15s
// gives a small window of de-dupe across tab switches without
// holding obviously-stale data when the user comes back to the page.
//
// Phase 5h.1.1 (2026-05-21): userId in queryKey to prevent cross-
// persona cache bleed. Backend RLS scopes responses per JWT, but the
// react-query cache keys on its key alone and would otherwise serve
// a cached PLATFORM-feed response to a TENANT caller landing on the
// same params during a JWT swap window. See Finding #50.
const STALE_MS = 15_000;

export function useAuditActivities(params?: AuditListParams) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["audit-activities", userId, params],
    queryFn: () => auditApi.list(params),
    enabled: !!userId,
    staleTime: STALE_MS,
  });
}

export function useAuditActivity(id: string | undefined) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["audit-activity", userId, id],
    queryFn: () => auditApi.get(id as string),
    enabled: !!userId && !!id,
  });
}
