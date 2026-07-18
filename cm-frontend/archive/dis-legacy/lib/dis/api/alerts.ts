import { disApiFetch, disQs } from "./client";
import type { ListResponse } from "@/lib/api/types";
import type {
  AlertEvent,
  AlertEventListParams,
  AlertRule,
  AlertRuleListParams,
} from "@/types/dis";

// Phase 5c.4d-events + 5c.4d-rules: read-only API surface. Acknowledge
// / resolve workflows + rule mutation defer to Phase 5d backend support,
// mirroring the validation / drift / freshness pattern.

export const alertsApi = {
  list: (params?: AlertEventListParams) =>
    disApiFetch<ListResponse<AlertEvent>>(
      `/api/v1/dis/alerts/events${disQs(params as Record<string, unknown> | undefined)}`,
    ),

  get: (id: string) =>
    disApiFetch<AlertEvent>(`/api/v1/dis/alerts/events/${id}`),

  listRules: (params?: AlertRuleListParams) =>
    disApiFetch<ListResponse<AlertRule>>(
      `/api/v1/dis/alerts/rules${disQs(params as Record<string, unknown> | undefined)}`,
    ),

  getRule: (id: string) =>
    disApiFetch<AlertRule>(`/api/v1/dis/alerts/rules/${id}`),
};
