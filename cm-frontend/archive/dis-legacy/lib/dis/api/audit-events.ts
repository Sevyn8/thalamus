import { disApiFetch, disQs } from "./client";

// Phase 5d.6: DIS audit-events read endpoint. POST publishing has
// existed since 5c.1c (lib/dis/audit.ts dispatcher). GET added in
// 5d.6 to drive the AuditPanel on the admin canonical-schema page.
//
// MSW persists into audit-events-store; deployed backend will
// replace with a real endpoint in Phase 5e+. URL stays the same.

export type AuditEventsListParams = {
  domain_id?: string;
  // Comma-joined in the wire; UI passes string[] and the helper
  // serializes.
  event_types?: string[];
  limit?: number;
  offset?: number;
};

export type AuditEventListItem = {
  id: string;
  event_type: string;
  occurred_at: string;
  user_id: string;
  user_name: string;
  domain_id?: string | null;
  field_id?: string | null;
  payload: Record<string, unknown>;
};

export type AuditEventsListResponse = {
  items: AuditEventListItem[];
  pagination: { total: number; offset: number; limit: number };
};

function toWireParams(
  params?: AuditEventsListParams,
): Record<string, unknown> | undefined {
  if (!params) return undefined;
  const out: Record<string, unknown> = {};
  if (params.domain_id) out.domain_id = params.domain_id;
  if (params.event_types && params.event_types.length > 0) {
    out.event_types = params.event_types.join(",");
  }
  if (typeof params.limit === "number") out.limit = params.limit;
  if (typeof params.offset === "number") out.offset = params.offset;
  return out;
}

export const auditEventsApi = {
  list: (params?: AuditEventsListParams) =>
    disApiFetch<AuditEventsListResponse>(
      `/api/v1/dis/audit-events${disQs(toWireParams(params))}`,
    ),
};
