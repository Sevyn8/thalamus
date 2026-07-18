import { apiFetch, qs } from "./client";
import type { ModulesResponse, MatrixResponse } from "@/types/api";
import type { components } from "@/types/openapi-generated";

// Phase 5n.1: routes through lib/api/client.ts, whose base URL is
// resolved at runtime via runtime-config (/api/config). Reads + writes
// shipped backend-side (Steps 6.15 + module-access GETs). Frontend
// write rebuild (matrix cell toggle) deferred to a later chunk.

export type ModuleMatrixParams = {
  sort?:
    | "name_asc"
    | "name_desc"
    | "created_at_asc"
    | "created_at_desc"
    | "tier_asc"
    | "tier_desc";
  tier?: "ENTERPRISE" | "MID_MARKET" | "SMB" | "SINGLE_STORE";
  status?: "ONBOARDING" | "TRIAL" | "ACTIVE" | "SUSPENDED";
  q?: string;
  limit?: number;
  offset?: number;
};

export type ModuleAccessRead = components["schemas"]["ModuleAccessRead"];

// Backend ModuleCode enum (Step 6.15). The frontend's hand-extended
// ModuleCode union (types/api.ts) is wider — adds DIS for launcher
// tile gating. The write endpoints reject DIS as 422 because DIS is
// not in the backend enum. Callers must not invoke enable/disable
// with DIS until DIS-as-module ships server-side.
export type WritableModuleCode = components["schemas"]["ModuleCode"];

export const modulesApi = {
  cards: () => apiFetch<ModulesResponse>(`/api/v1/module-access/modules`),

  matrix: (params?: ModuleMatrixParams) =>
    apiFetch<MatrixResponse>(
      `/api/v1/module-access/matrix${qs(params as Record<string, unknown> | undefined)}`,
    ),

  // Idempotency-Key generated per call (not per mutation-hook instantiation):
  // a 500-then-retry produces two distinct intents and must use two keys.
  enable: (tenantId: string, moduleCode: WritableModuleCode) =>
    apiFetch<ModuleAccessRead>(
      `/api/v1/module-access/${tenantId}/${moduleCode}/enable`,
      {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
      },
    ),

  disable: (tenantId: string, moduleCode: WritableModuleCode) =>
    apiFetch<ModuleAccessRead>(
      `/api/v1/module-access/${tenantId}/${moduleCode}/disable`,
      {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
      },
    ),
};
