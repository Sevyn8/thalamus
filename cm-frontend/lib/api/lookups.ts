import { apiFetch } from "./client";
import type { Lookups, LookupItem } from "@/types/api";

// Backend's lookup catalog (per Sanjeev's handoff §4 + Chunk 4 verification).
// Required `?lists=` query param; response wrapped in `{ lookups: { ... } }`
// with singular keys (tenant_tier, not tenant_tiers). The adapter normalizes
// to the frontend's discrete plural-keyed `Lookups` shape so consumers stay
// stable across MSW (plural keys) and real backend (singular keys).
const REQUESTED_LISTS = [
  "tenant_tier",
  "tenant_region",
  "tenant_status",
  "tenant_industry",
] as const;

type LookupsBatchResponse = {
  lookups?: Record<string, LookupItem[]>;
};

const SINGULAR_TO_PLURAL: Record<string, keyof Lookups> = {
  tenant_tier: "tenant_tiers",
  tenant_region: "tenant_regions",
  tenant_status: "tenant_statuses",
  tenant_industry: "tenant_industries",
};

function emptyLookups(): Lookups {
  return {
    tenant_tiers: [],
    tenant_industries: [],
    tenant_regions: [],
    tenant_statuses: [],
    user_statuses: [],
    modules: [],
    org_node_types: [],
    permission_actions: [],
    permission_scopes: [],
    role_codes: [],
  };
}

function adaptLookups(response: LookupsBatchResponse): Lookups {
  const result = emptyLookups();
  const incoming = response.lookups ?? {};
  for (const [key, items] of Object.entries(incoming)) {
    // Backend sends singular keys (tenant_tier); MSW sends plural keys
    // (tenant_tiers). Try singular→plural first, fall back to identity for
    // plural keys MSW already produces. Unknown keys silently dropped.
    const pluralKey = SINGULAR_TO_PLURAL[key] ?? (key as keyof Lookups);
    if (pluralKey in result) {
      result[pluralKey] = [...items].sort(
        (a, b) => a.display_order - b.display_order,
      );
    }
  }
  return result;
}

// Phase 5n.1: routes through lib/api/client.ts, whose base URL is
// resolved at runtime via runtime-config (/api/config).
export const lookupsApi = {
  all: async (): Promise<Lookups> => {
    const response = await apiFetch<LookupsBatchResponse>(
      `/api/v1/lookups?lists=${REQUESTED_LISTS.join(",")}`,
    );
    return adaptLookups(response);
  },
};
