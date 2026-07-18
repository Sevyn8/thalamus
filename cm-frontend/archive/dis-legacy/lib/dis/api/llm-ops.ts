import { disApiFetch } from "./client";
import type {
  LlmOpsFleetResponse,
  LlmOpsTenantDetail,
  LlmOpsTimeWindow,
} from "@/types/dis";

// Phase 5c.8c: LLM ops admin (read-only). PLATFORM-only on the
// server. Same window param across both endpoints.

export const llmOpsApi = {
  fleet: (window: LlmOpsTimeWindow) =>
    disApiFetch<LlmOpsFleetResponse>(
      `/api/v1/dis/admin/llm-ops?window=${encodeURIComponent(window)}`,
    ),

  tenant: (tenantId: string, window: LlmOpsTimeWindow) =>
    disApiFetch<LlmOpsTenantDetail>(
      `/api/v1/dis/admin/llm-ops/${encodeURIComponent(tenantId)}?window=${encodeURIComponent(window)}`,
    ),
};
