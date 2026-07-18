"use client";

import { useQuery } from "@tanstack/react-query";

import {
  auditEventsApi,
  type AuditEventsListParams,
} from "@/lib/dis/api/audit-events";

// Phase 5d.6: read-only audit-events fetcher. AuditPanel passes
// { domain_id, event_types: [...] } scoped to the canonical-schema
// event family. staleTime: 0 — audits are written by user actions
// on the same page, so React Query's auto-invalidate after the
// POST round-trip is the desired refresh signal.

export function useAuditEvents(params?: AuditEventsListParams) {
  return useQuery({
    queryKey: ["dis", "audit-events", params],
    queryFn: () => auditEventsApi.list(params),
  });
}
