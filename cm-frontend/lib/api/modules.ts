import { apiFetch, qs } from "./client";
import type {
  ModulesResponse,
  MatrixResponse,
  MatrixRow,
  MyModulesResponse,
} from "@/types/api";
import type { components } from "@/types/openapi-generated";

// Routes through lib/api/client.ts, whose base URL is resolved at
// runtime via runtime-config (/api/config).

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

// Backend ModuleCode enum (the enable/disable path-param vocabulary).
// DIS shipped server-side (added to the backend enum + module_code
// lookups), so it is now a real writable module here: enable/disable
// accept DIS like any other module, and the Module Access matrix toggles
// it. ADMIN remains structurally non-disable-able (backend DDL
// constraint); the matrix keeps ADMIN locked.
export type WritableModuleCode = components["schemas"]["ModuleCode"];

export const modulesApi = {
  cards: () => apiFetch<ModulesResponse>(`/api/v1/module-access/modules`),

  matrix: (params?: ModuleMatrixParams) =>
    apiFetch<MatrixResponse>(
      `/api/v1/module-access/matrix${qs(params as Record<string, unknown> | undefined)}`,
    ),

  // Caller-state read of the caller's OWN tenant's enabled
  // modules. GATE_EXEMPT backend endpoint — a TENANT persona can power
  // the launcher without an admin governance grant (the matrix endpoint
  // is gated on ADMIN.TENANTS.VIEW.TENANT).
  myModules: () =>
    apiFetch<MyModulesResponse>(`/api/v1/module-access/me`),

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

// Sentinel thrown when the tenant's module row cannot be resolved from the
// fleet matrix (never falls back to an empty section; the caller renders an
// explicit error + retry).
export class TenantModuleRowNotFoundError extends Error {
  constructor(tenantId: string) {
    super(`Module row not found for tenant ${tenantId}`);
    this.name = "TenantModuleRowNotFoundError";
  }
}

// Deterministic per-tenant module-row lookup. The matrix endpoint is
// fleet-wide with no tenant_id filter (verified in backend code: `q` is a
// case-insensitive ILIKE substring on tenants.name only), so a name-based
// fetch can miss on rename or pagination. Fast path: q by name, match
// STRICTLY on tenant_id. Fallback: page the unfiltered matrix, still
// matching on tenant_id, bounded. If unresolved, throw (no empty section).
const _MATRIX_PAGE = 200;
const _MAX_PAGES = 50; // 10k tenants ceiling; far above any real fleet

export async function resolveTenantModuleRow(
  tenantId: string,
  tenantName?: string,
): Promise<MatrixRow> {
  if (tenantName) {
    const byName = await modulesApi.matrix({ q: tenantName, limit: _MATRIX_PAGE });
    const hit = byName.items.find((r) => r.tenant_id === tenantId);
    if (hit) return hit;
  }
  let offset = 0;
  for (let page = 0; page < _MAX_PAGES; page += 1) {
    const res = await modulesApi.matrix({ limit: _MATRIX_PAGE, offset });
    const hit = res.items.find((r) => r.tenant_id === tenantId);
    if (hit) return hit;
    offset += _MATRIX_PAGE;
    if (offset >= res.pagination.total) break;
  }
  throw new TenantModuleRowNotFoundError(tenantId);
}
