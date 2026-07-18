import { disApiFetch, disQs } from "./client";
import type { ListResponse } from "@/lib/api/types";
import type {
  ValidationListParams,
  ValidationRule,
  ValidationViolation,
} from "@/types/dis";

// Phase 5c.4a: read-only API surface — list rules + get rule + per-rule
// violations log. Rule create/edit/disable lands when the DIS backend
// supports rule mutation (Phase 5d or later).

export const validationApi = {
  list: (params?: ValidationListParams) =>
    disApiFetch<ListResponse<ValidationRule>>(
      `/api/v1/dis/validation/rules${disQs(params as Record<string, unknown> | undefined)}`,
    ),

  get: (id: string) =>
    disApiFetch<ValidationRule>(`/api/v1/dis/validation/rules/${id}`),

  getViolations: (ruleId: string, params?: { offset?: number; limit?: number }) =>
    disApiFetch<ListResponse<ValidationViolation>>(
      `/api/v1/dis/validation/rules/${ruleId}/violations${disQs(
        params as Record<string, unknown> | undefined,
      )}`,
    ),
};
