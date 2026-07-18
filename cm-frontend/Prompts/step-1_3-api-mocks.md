# Prompt — Step 1.3: API client and mock infrastructure

> Paste this after Step 1.2 is committed.

---

## Pre-flight

```bash
pwd
git log --oneline -5             # confirm Step 1.2 commit at top
pnpm tsc --noEmit                # must exit zero
pnpm dev                         # in another terminal
# verify /dev/login → pick persona → /superadmin/dashboard works
```

If the auth flow from Step 1.2 is broken, STOP. Do not start Step 1.3 until the auth flow works end-to-end.

Read `BUILD_PLAN.md` Step 1.3 in full. Read `README.md` sections "API contract (locked for v0)" and "Mock data strategy" before writing any code.

---

## Step ID and intent

**Step 1.3** — Data plane working end-to-end with mocks. After this step, a component can call `useTenants()` and render the 7 fixture tenants.

This is a CLAUDE_CODE step. Three layers: typed API clients, MSW handlers, TanStack Query hooks. Per-endpoint mock toggle.

---

## Scope in

### 1. Folder structure to create

```
lib/
  api/
    client.ts          # base typed fetch wrapper
    types.ts           # shared response types (envelope, error, pagination)
    tenants.ts         # one file per resource
    users.ts
    org-nodes.ts
    roles.ts
    audit-logs.ts
    modules.ts
    guardrails.ts
    lookups.ts
    dashboard.ts       # KPIs, top-tenants, recent-activity composite
  hooks/
    use-tenants.ts
    use-users.ts
    use-org-nodes.ts
    use-roles.ts
    use-audit-logs.ts
    use-modules.ts
    use-guardrails.ts
    use-lookups.ts
    use-dashboard.ts
mocks/
  config.ts            # per-endpoint mock|real toggle
  browser.ts           # MSW browser worker setup (dev-only)
  server.ts            # MSW Node setup (placeholder for tests; not used in v0)
  handlers/
    tenants.ts
    users.ts
    org-nodes.ts
    roles.ts
    audit-logs.ts
    modules.ts
    guardrails.ts
    lookups.ts
    dashboard.ts
    index.ts           # exports all handlers as one array
  fixtures/
    tenants.json
    users.json
    org-nodes.json
    roles.json
    permissions.json
    audit-logs.json
    modules.json
    guardrails.json
    lookups.json
    dashboard.json
types/
  api.ts               # response types per resource (hand-written for v0; OpenAPI-generated later)
```

### 2. Base API client (`lib/api/client.ts`)

Typed fetch wrapper that:

- Reads `NEXT_PUBLIC_API_BASE_URL` from env
- Attaches `Authorization: Bearer <jwt>` from `lib/auth/client.ts` `getToken()`
- Sets `Content-Type: application/json` for write methods (even though v0 has no writes; future-proof)
- Parses success responses as JSON
- On non-2xx, parses the body as `{code, message, details, request_id}` and throws a typed `ApiError`
- Returns the typed `X-Request-Id` header for logging

```typescript
export class ApiError extends Error {
  code: string;
  details: unknown;
  requestId: string;
  status: number;
  constructor(args: { code: string; message: string; details: unknown; requestId: string; status: number; });
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T>;
```

### 3. Shared response types (`lib/api/types.ts`)

```typescript
export type Pagination = { total: number; offset: number; limit: number };
export type ListResponse<T> = { items: T[]; pagination: Pagination };
export type ApiErrorBody = { code: string; message: string; details: unknown; request_id: string };
```

### 4. Per-resource API modules

Each file in `lib/api/<resource>.ts` exports typed functions calling `apiFetch`. Example for tenants:

```typescript
// lib/api/tenants.ts
import { apiFetch } from "./client";
import type { ListResponse } from "./types";
import type { Tenant, TenantDetail } from "@/types/api";

export const tenantsApi = {
  list: (params?: { tier?: string; search?: string; sort?: string; offset?: number; limit?: number }) =>
    apiFetch<ListResponse<Tenant>>(`/v1/tenants${qs(params)}`),
  get: (id: string) =>
    apiFetch<TenantDetail>(`/v1/tenants/${id}`),
  stats: () =>
    apiFetch<TenantStats>(`/v1/tenants/stats`),
};
```

Mirror this pattern for all 9 resources. Function signatures should match the GET-only endpoints listed in `tenants-api-contract-v0.md` (in the backend repo's project files, not yet copied here — base your understanding on what was discussed in this conversation thread).

For v0, only implement GET. Other methods (POST/PATCH/DELETE) are out of scope; do not add them.

### 5. Response types (`types/api.ts`)

Hand-write the TypeScript types for v0 based on the API contract recommendations. Snake_case field names. Examples:

```typescript
export type Tenant = {
  id: string;
  name: string;
  display_code: string;
  country: string;
  region: "US" | "EU";
  industry: string;
  tier: "ENTERPRISE" | "MID_MARKET" | "SMB" | "SINGLE_STORE";
  status: "ONBOARDING" | "TRIAL" | "ACTIVE" | "SUSPENDED" | "TERMINATED";
  monthly_revenue_usd: string | null;
  num_stores: number;
  num_users: number;
  modules: { code: string; name: string }[];
  created_at: string;
  updated_at: string;
};
```

Include types for: `Tenant`, `TenantDetail`, `TenantStats`, `User`, `UserDetail`, `OrgNode`, `OrgTree`, `OrgSummary`, `Role`, `RoleDetail`, `Permission`, `AuditEvent`, `AuditDetail`, `ModuleSummary`, `TenantModuleRow`, `Guardrail`, `Lookups`, `DashboardKPIs`, `TopTenantRow`, `RecentActivityRow`.

### 6. Mock config (`mocks/config.ts`)

```typescript
export type MockMode = "mock" | "real";

export const MOCK_CONFIG: Record<string, MockMode> = {
  tenants: "mock",
  "tenant-stats": "mock",
  users: "mock",
  "org-nodes": "mock",
  "org-summary": "mock",
  roles: "mock",
  permissions: "mock",
  "audit-logs": "mock",
  modules: "mock",
  "tenant-modules": "mock",
  guardrails: "mock",
  lookups: "mock",
  dashboard: "mock",
};
```

All default to `"mock"` for v0. Flipping to `"real"` happens during the wiring phase.

### 7. MSW handlers

Each `mocks/handlers/<resource>.ts` exports an array of MSW request handlers covering the GET endpoints for that resource. Handlers consult `MOCK_CONFIG`; if the entry is `"real"`, the handler calls `passthrough()` so the request reaches the real backend.

Example pattern:

```typescript
import { http, HttpResponse, passthrough } from "msw";
import fixtures from "../fixtures/tenants.json";
import { MOCK_CONFIG } from "../config";

export const tenantsHandlers = [
  http.get("/v1/tenants", ({ request }) => {
    if (MOCK_CONFIG.tenants === "real") return passthrough();
    const url = new URL(request.url);
    const tier = url.searchParams.get("tier");
    const search = url.searchParams.get("search");
    let items = fixtures;
    if (tier) items = items.filter(t => tier.split(",").includes(t.tier));
    if (search) items = items.filter(t => t.name.toLowerCase().includes(search.toLowerCase()));
    return HttpResponse.json({
      items,
      pagination: { total: items.length, offset: 0, limit: 20 },
    });
  }),
  // ... handlers for /v1/tenants/{id}, /v1/tenants/stats, etc.
];
```

`mocks/handlers/index.ts` aggregates all handlers:

```typescript
import { tenantsHandlers } from "./tenants";
// ...
export const handlers = [...tenantsHandlers, ...usersHandlers, /* etc */];
```

### 8. Fixture data

Source from Appendix E of `Ithina_Admin_Frontend.md` (you have notes from the bootstrap context):

- 7 tenants (Buc-ee's, Żabka, SmartStore, FreshMart, CornerStop, GreenLeaf, Infomil) with the exact data from Appendix E
- Buc-ee's org tree (HQ + 2 regions + 3 stores) per Appendix E
- 17 users (Anjali, Devon, Kira, Marcus, Jamie, Tasha, Hector, Anna, Piotr, Magda, Priya, Liam, Daniel, plus 4 more if needed)
- Roles: Super Admin, Platform Admin, Module Admin, Support Admin, Owner, Pricing Manager, Category Manager, Merchandising, Marketing, Store Operations, Store Manager, Associate, Night Shift Lead, Finance, IT/Analytics
- ~30 permissions covering Pricing OS / Markdowns / VIEW + CONFIGURE + EXECUTE + APPROVE etc., plus Admin / Users / Roles / Audit Log
- 5 guardrails (Markdown >30%, Bulk Donation Routing, Promo Activation Tenant-Wide, Role Assignment >Manager, Module Enable/Disable)
- ~20 audit events covering the action labels in Section 10 of the frontend spec
- Tenant module enablement matching what each tenant has per Appendix E
- Lookups for tiers, industries, regions, statuses, modules, node_types

Use the exact UUIDs from `tenants-api-contract-v0.md` examples where possible (e.g., Buc-ee's id is `a1b2c3d4-0003-4000-8000-000000000003`). Where IDs aren't given, generate UUIDs and stay consistent across fixtures (the same Buc-ee's UUID in `tenants.json`, `users.json`, `org-nodes.json`).

### 9. MSW browser worker

Create `mocks/browser.ts`:

```typescript
import { setupWorker } from "msw/browser";
import { handlers } from "./handlers";
export const worker = setupWorker(...handlers);
```

Initialise the worker only in dev. In `app/providers.tsx`:

```typescript
"use client";
import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

export function Providers({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(process.env.NODE_ENV !== "development");
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
  }));

  useEffect(() => {
    if (process.env.NODE_ENV === "development") {
      import("../mocks/browser").then(({ worker }) =>
        worker.start({ onUnhandledRequest: "bypass" }).then(() => setReady(true))
      );
    }
  }, []);

  if (!ready) return null;
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
```

Run `pnpm dlx msw init public/ --save` to install the MSW service worker file.

Wrap `app/layout.tsx` body with `<Providers>`.

### 10. TanStack Query hooks

Each `lib/hooks/use-<resource>.ts` exports query hooks consuming the API modules. Example:

```typescript
// lib/hooks/use-tenants.ts
import { useQuery } from "@tanstack/react-query";
import { tenantsApi } from "@/lib/api/tenants";

export function useTenants(params?: Parameters<typeof tenantsApi.list>[0]) {
  return useQuery({
    queryKey: ["tenants", params],
    queryFn: () => tenantsApi.list(params),
  });
}

export function useTenant(id: string) {
  return useQuery({
    queryKey: ["tenant", id],
    queryFn: () => tenantsApi.get(id),
    enabled: !!id,
  });
}

export function useTenantStats() {
  return useQuery({
    queryKey: ["tenant-stats"],
    queryFn: tenantsApi.stats,
    staleTime: 60_000,
  });
}
```

Mirror the pattern for all resources. Set staleTime per the cache hints in `tenants-api-contract-v0.md` performance contract sections (lookups: 1h, stats: 60s, default: 30s).

### 11. Smoke verification

Update `app/superadmin/dashboard/page.tsx` (the placeholder from Step 1.2) to call `useTenants()` and render the count. Just enough to verify the data plane works end-to-end:

```typescript
"use client";
import { useTenants } from "@/lib/hooks/use-tenants";

export default function DashboardPage() {
  const { data, isLoading, error } = useTenants();
  if (isLoading) return <div>Loading...</div>;
  if (error) return <div>Error: {error.message}</div>;
  return <div>Dashboard — {data?.items.length} tenants loaded</div>;
}
```

Visit the page after logging in via persona switcher. Should see "Dashboard — 7 tenants loaded".

---

## Scope out

- No real chrome (that is Step 1.4)
- No real dashboard, no real pages (Phase 2)
- No write endpoints, no mutations
- No tests; tests are out of v0 scope
- No OpenAPI generation; types are hand-written for v0

---

## Acceptance criteria

1. All 9 resources have API client modules under `lib/api/`
2. All 9 resources have MSW handlers under `mocks/handlers/`
3. All 9 fixtures exist under `mocks/fixtures/` with realistic demo data
4. `mocks/config.ts` defaults all to `"mock"`
5. MSW service worker installed in `public/`
6. `app/providers.tsx` wires QueryClient + MSW worker for dev
7. All hooks under `lib/hooks/use-*.ts` exist and are typed
8. `app/superadmin/dashboard/page.tsx` calls `useTenants()` and renders the count
9. Visiting the dashboard after persona login shows "Dashboard — 7 tenants loaded"
10. `pnpm tsc --noEmit` exits zero
11. No console errors in browser
12. `BUILD_PLAN.md` Step 1.3 flipped to DONE

---

## After completing the step

1. Confirm acceptance
2. Report files added with line counts (this will be the largest step by file count)
3. Flag any contract ambiguities you noticed while writing types — these are useful inputs to the wiring phase
4. Update `BUILD_PLAN.md`
5. Propose commit:
   ```
   git add -A
   git commit -m "Step 1.3: API client + MSW handlers + TanStack Query hooks"
   ```
6. Wait for user direction before Step 1.4

---

## If you hit a snag

- MSW v2 vs v1 API differs: check the installed version in `package.json`. Use v2 syntax (`http.get`, `HttpResponse.json`). Do not mix.
- TanStack Query v5 vs v4 differs: check installed version. v5 uses object form for `useQuery({queryKey, queryFn})`.
- Type drift between fixtures and `types/api.ts`: stop and align. The fixture is the contract for now; if the type doesn't match, update the type, not the fixture.
- A fixture detail you don't have (e.g., a specific user's MFA state): make a sensible default and note it in your final report so the user can correct if needed.
