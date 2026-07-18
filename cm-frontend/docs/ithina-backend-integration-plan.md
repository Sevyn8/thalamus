# Ithina backend integration plan

Phase 5e — current-state inventory + chunk sequence for wiring Sanjeev's deployed backend into the frontend. Companion to `docs/frontend-backend-wiring-handoff.md` (forward-looking handoff). Authored 2026-05-07 against backend HEAD `d723b52`.

---

## 1. Context

Sanjeev has shipped 8 new endpoints since the frontend's last OpenAPI sync (Phase 4d). All 8 are deployed and live (curl-verified 401-not-404 on a sample). The frontend has placeholder API modules anticipating some of these, but with **shape mismatches** that don't match Sanjeev's deployed contract. This doc inventories the gaps and proposes a chunk sequence.

**Scope:** integrate the 8 new endpoints in 3 chunks (RBAC catalog → Module Access → Dashboard stats). MSW retirement is per-surface flip via `MOCK_CONFIG`; existing handlers stay as dev-mode fallback.

**Out of scope this phase:**
- Audit log endpoints (not yet shipped backend-side; tracked as Step 6.2 forward)
- Tenant-modules write surface (forward note `MODULE-ACCESS-WRITE`)
- Custom-role-creation write surface (forward note `CUSTOM-ROLES-REAL`)

---

## 2. Endpoint diff (paths)

### 2.1 New paths (8)

| Path | Endpoint family | Frontend consumer (target) | Current frontend state |
|---|---|---|---|
| `GET /api/v1/permissions` | RBAC catalog | `lib/api/roles.ts:permissions()` | Placeholder exists; **wrong response shape** — frontend expects `ListResponse<Permission>` but backend returns `PermissionListResponse {items, pagination}` (matches structurally; type rename only) |
| `GET /api/v1/roles` | RBAC catalog | `lib/api/roles.ts:list()` | Placeholder exists; **breaking shape mismatch** — frontend expects `ListResponse<Role>` (flat); backend returns `RoleListResponse {platform_roles: AudienceBlock, tenant_roles: AudienceBlock}` (pre-grouped) |
| `GET /api/v1/roles/{role_id}/permissions` | RBAC catalog | None — placeholder method `lib/api/roles.ts:get(id)` returns `RoleDetail` from `/api/v1/roles/{id}` (path doesn't exist on backend) | **No matching consumer**; needs new hook `useRolePermissions(roleId)` |
| `GET /api/v1/permission-matrix` | RBAC catalog | None | **No consumer**; needs new hook `usePermissionMatrix()` |
| `GET /api/v1/module-access/modules` | Module Access | `lib/api/modules.ts:summary()` calls `/api/v1/modules` (wrong path) | **Wrong path AND wrong shape**; backend uses `/module-access/modules` returning `ModulesResponse {items: ModuleCard[]}` (no pagination, fixed 6) |
| `GET /api/v1/module-access/matrix` | Module Access | `lib/api/modules.ts:tenantModules()` calls `/api/v1/tenant-modules` (wrong path) | **Wrong path AND wrong shape**; backend uses `/module-access/matrix` with paginated `MatrixResponse {items: MatrixRow[], pagination}` |
| `GET /api/v1/dashboard/fleet-stats` | Dashboard stats | None — `lib/api/dashboard.ts:kpis()` calls `/api/v1/dashboard/kpis` (path doesn't exist) | **No matching consumer**; needs new hook `useFleetStats()` |
| `GET /api/v1/dashboard/governance-stats` | Dashboard stats | None | **No consumer**; needs new hook `useGovernanceStats()` |

### 2.2 Shared paths (12) — schema-shape diff

| Path | Schema diff vs frontend pinned snapshot | Action |
|---|---|---|
| `GET /api/v1/health`, `/ready` | None | None |
| `GET /api/v1/lookups` | None | None |
| `GET /api/v1/platform-users` (list + detail) | None expected (Phase 4d wired) | Verify after `pnpm gen:types` diff |
| `GET /api/v1/tenant-users` (list + detail) | None expected (Phase 4d wired) | Verify after `pnpm gen:types` diff |
| `GET /api/v1/tenants` (list + stats + detail) | **Possible aggregate sort keys added** per backend's Step 6.4 work — `num_users_active_*`, `num_stores_*` referenced in module-access.md as "exposed by `/tenants`". Frontend's `TenantListParams` may need updating. | Verify in 5e.2 prep; bundle into the RBAC chunk if light, or stand up a hotfix |
| `GET /api/v1/tenants/{id}/org-tree` + `org-nodes/{id}/children` | None expected (Phase 4e wired) | Verify after `pnpm gen:types` diff |

---

## 3. Per-endpoint response shapes (8 new)

Detailed contract reference. Cross-references: backend's per-endpoint docs at `ithina-retail-admin-backend/docs/endpoints/{rbac,module-access,dashboard}.md`.

### 3.1 RBAC catalog (4 endpoints)

**`GET /api/v1/permissions`** — flat catalogue, paginated.

```ts
type PermissionRead = {
  id: string;            // UUIDv7
  module: string;        // ADMIN / PRICING_OS / PERISHABLES_ASSISTANT / PROMOTIONS_ASSISTANT
  resource: string;
  action: string;
  scope: string;         // GLOBAL / TENANT / STORE
  code: string;          // module.resource.action.scope (UNIQUE)
  description: string | null;
  created_at: string;
  updated_at: string;
};
type PermissionListResponse = {
  items: PermissionRead[];
  pagination: { total: number; offset: number; limit: number };
};
```

Both user types see all rows (reference data, no audience filter). Default sort `module_asc` (compound). Query params: `module`, `scope`, `sort`, `offset`, `limit`.

**`GET /api/v1/roles`** — pre-grouped by audience, **deliberate D-30 exception** (no top-level pagination).

```ts
type RoleListItem = {
  id: string;
  name: string;
  code: string;
  description: string | null;
  status: "ACTIVE" | "INACTIVE" | "ARCHIVED";
  is_system: boolean;
  user_count: number;     // RLS-scoped for TENANT JWTs
  created_at: string;
  updated_at: string;
};
type AudienceBlock = { items: RoleListItem[]; total: number };
type RoleListResponse = {
  platform_roles: AudienceBlock;  // empty for TENANT JWTs
  tenant_roles: AudienceBlock;
};
```

PLATFORM sees both blocks; TENANT sees `platform_roles: {items: [], total: 0}`. Per-block `offset`/`limit` query params apply within each block. `audience` enum NOT in items (implied by container key).

**`GET /api/v1/roles/{role_id}/permissions`** — parent-echo envelope, **deliberate D-30 exception** (no pagination, sub-resource).

```ts
type RolePermissionsResponse = {
  role_id: string;        // echo of path param (race-condition guard)
  role_name: string;      // saves a cross-lookup against E1's cache
  items: PermissionRead[];
};
```

Cross-audience lookups return **404 (`ROLE_NOT_FOUND`), not 403** — anti-information-disclosure. Frontend handles 404 gracefully.

**`GET /api/v1/permission-matrix`** — render-ready grid, **deliberate D-30 exception** (no pagination, no filters, single shape).

```ts
type PermissionMatrixRoleColumn = {
  id: string;
  name: string;
  audience: "PLATFORM" | "TENANT";
};
type PermissionMatrixRow = {
  id: string;
  module: string;
  module_label: string;        // resolved via lookups, COALESCE-fallback to enum code
  resource: string;
  resource_label: string;
  action: string;
  action_label: string;
  scope: string;
  scope_label: string;
  cells: boolean[];            // position-aligned with roles[]
};
type PermissionMatrixResponse = {
  roles: PermissionMatrixRoleColumn[];
  rows: PermissionMatrixRow[];
};
```

**Hard invariant M2:** `len(row.cells) == len(roles)` for every row. Position-based cell rendering, no key lookup. TENANT JWTs receive shrunk `roles[]` (TENANT-audience only) with `cells[]` correspondingly shorter.

### 3.2 Module Access (2 endpoints)

**`GET /api/v1/module-access/modules`** — 6 module cards, **fixed cardinality**.

```ts
type ModuleCode =
  | "ROOS" | "GOAL_CONSOLE" | "PRICING_OS"
  | "PERISHABLES_ASSISTANT" | "PROMOTIONS_ASSISTANT" | "ADMIN";
type ModuleCard = {
  module_code: ModuleCode;
  module_label: string;                 // server-resolved via lookups
  enabled_count: number;                // RLS-scoped
  total_active_trial_tenants: number;   // denominator
};
type ModulesResponse = { items: ModuleCard[] };  // always 6
```

Always exactly 6 entries. Order: `lookups.display_order ASC, code ASC` — ROOS / GOAL_CONSOLE / PRICING_OS / PERISHABLES_ASSISTANT / PROMOTIONS_ASSISTANT / ADMIN. **Hard invariant:** `items[i].module_code === matrix.items[*].cells[i].module_code` (position-aligned).

**`GET /api/v1/module-access/matrix`** — paginated tenant × module grid.

```ts
type MatrixCell = {
  module_code: ModuleCode;
  status: "ENABLED" | "DISABLED";       // synthesized backend-side
};
type MatrixRow = {
  tenant_id: string;
  name: string;
  tier: "ENTERPRISE" | "MID_MARKET" | "SMB" | "SINGLE_STORE" | null;
  tier_label: string | null;            // server-resolved
  status: "ONBOARDING" | "TRIAL" | "ACTIVE" | "SUSPENDED";
  status_label: string;
  cells: MatrixCell[];                  // always 6, position-aligned
};
type MatrixResponse = {
  items: MatrixRow[];
  pagination: { limit: number; offset: number; total: number };
};
```

Query params: `sort` (default `tier_asc`, options: `name_*`, `created_at_*`, `tier_*`), `tier`, `status`, `q` (name ILIKE), `limit` (≤200), `offset`. **TERMINATED tenants structurally absent** from the row set — `?status=TERMINATED` returns 422.

### 3.3 Dashboard stats (2 endpoints)

**`GET /api/v1/dashboard/fleet-stats`** — cards 1-4, all real in v0.

```ts
type DeltaBlock = {
  value: number | null;
  direction: "up" | "down" | "flat" | null;
  window: "7d" | "30d" | "24h" | "monthly" | null;
  available: boolean;
};
type FleetStatsResponse = {
  active_tenants: { value: number; total: number; sub_text: string; delta: DeltaBlock; available: boolean };
  platform_users: { value: number; sub_text: string; delta: DeltaBlock; available: boolean };
  stores:         { value: number; distinct_countries: number; sub_text: string; delta: null; available: boolean };
  mrr_aggregated: { value: string; currency: string; sub_text: string; delta: DeltaBlock; available: boolean };
};
```

`mrr_aggregated.value` is **string with 2 decimal places** (e.g., `"308100.00"`); not number. `delta.available` may be `false` even when card-level `available: true` (e.g., `mrr_aggregated.delta.available === false` while `mrr_aggregated.available === true`).

**`GET /api/v1/dashboard/governance-stats`** — cards 5-8; **3 of 4 stubbed in v0**.

```ts
type UnavailableReason =
  | "approvals_table_not_built"
  | "audit_logs_or_guardrails_not_wired"
  | "custom_role_creation_not_shipped";

type StubbableCard<T> = T & {
  available: boolean;
  unavailable_reason?: UnavailableReason;
};

type GovernanceStatsResponse = {
  pending_approvals:    StubbableCard<{ value: number; sub_text: string; delta: null }>;
  guardrails_fired_24h: StubbableCard<{ value: number; escalations: number; sub_text: string; delta: null }>;
  custom_roles:         StubbableCard<{ value: number; total: number; sub_text: string; delta: null }>;
  modules_deployed:                  { value: number; sub_text: string; delta: null; available: boolean };  // real in v0
};
```

**Render gate**: `available: false` cards must show "coming soon" treatment. Type-stable sentinel `value: 0` is NOT meaningful when `available: false`. Frontend MUST gate on `available`, not on `value > 0`.

---

## 4. Cross-cutting design intent

Captured from backend's per-endpoint docs. Frontend should match these conventions.

### 4.1 Deliberate D-30 exceptions (non-paginated envelopes)

| Endpoint | Reason |
|---|---|
| `/roles` (E1) | Pre-grouped shape doesn't compose with cross-group pagination |
| `/roles/{id}/permissions` (E3) | Sub-resource; pagination has no meaningful seat |
| `/permission-matrix` (E6) | Render-ready, single-shape, returned in full |
| `/dashboard/fleet-stats` + `/governance-stats` | Card-shaped UI bundle, not a paginatable collection |
| `/module-access/modules` | Fixed 6-row cardinality |

Frontend type-aliases should NOT wrap these in `ListResponse<T>`. Each gets a bespoke response type.

### 4.2 Append-only contract (D-31)

Field semantics, once shipped, are frozen. New variants land via new field names. Frontend code defensively against:
- `unavailable_reason` vocabulary may extend (treat as `string` widening, not breaking)
- `available` flag stays stable
- Card field sets stay stable when stub flips to real (only `available`, `value`, `unavailable_reason` change)

### 4.3 Server-side label resolution

**New convention from Step 6.7 onward.** Enum-coded fields carry sibling `<field>_label` resolved via JOIN against `lookups` with `COALESCE(display_name, code)` fallback.

| Endpoint | Label-bearing fields |
|---|---|
| `/module-access/modules` | `module_label` |
| `/module-access/matrix` | `module_label` (on cells), `tier_label`, `status_label` |
| `/permission-matrix` | `module_label`, `resource_label`, `action_label`, `scope_label` (on rows) |

**Older endpoints stay bare-enum** (no labels). Frontend keeps client-side label tables for those.

### 4.4 Position-aligned arrays (hard invariants)

| Pair | Invariant |
|---|---|
| `/permission-matrix.roles[i] ↔ rows[*].cells[i]` | M1/M2: position-based grant; `len(cells) == len(roles)` |
| `/module-access/modules.items[i] ↔ /module-access/matrix.items[*].cells[i]` | Both ordered by `lookups.display_order ASC, code ASC` |

Frontend renders by index. NOT by id-keyed lookup.

### 4.5 Audience filtering (vs RLS)

Three different mechanisms, similar effect:

| Surface | Mechanism |
|---|---|
| `roles` / `role_permissions` | Audience filter at app layer (tables are platform-global, no RLS) |
| `permissions` | None — open reference data |
| `module-access/*`, `dashboard/*`, `tenants/*`, `tenant-users/*`, `org-tree/*` | RLS via `app.tenant_id` / `app.user_type` GUCs |

Cross-audience role lookups (TENANT JWT → PLATFORM role) return **404 (`ROLE_NOT_FOUND`), not 403** — anti-information-disclosure.

---

## 5. Frontend lib/api/* placeholder mismatches

Walk-through of the 3 affected files. Other files in `lib/api/` (tenants, platform-users, tenant-users, org-nodes, lookups, audit-logs, guardrails, notifications) are either Phase 4 wired or MSW-only with no backend equivalent yet.

### 5.1 `lib/api/roles.ts` (3 methods)

```ts
// CURRENT (placeholders, wrong shapes):
list:        () => apiFetch<ListResponse<Role>>(`/api/v1/roles`)
get:         (id) => apiFetch<RoleDetail>(`/api/v1/roles/${id}`)        // path doesn't exist
permissions: () => apiFetch<ListResponse<Permission>>(`/api/v1/permissions`)
```

**Gap:**
- `list()` shape — `ListResponse<Role>` (flat) → `RoleListResponse` (pre-grouped). Breaking; consumers must rewrite.
- `get(id)` — `/api/v1/roles/{id}` does NOT exist on backend. Replace with `getPermissions(roleId)` calling `/api/v1/roles/{role_id}/permissions` returning `RolePermissionsResponse`.
- `permissions()` shape — close (`{items, pagination}`); type rename to `PermissionListResponse` + `PermissionRead`.
- New method needed: `matrix()` → `/api/v1/permission-matrix` returning `PermissionMatrixResponse`.

### 5.2 `lib/api/modules.ts` (2 methods)

```ts
// CURRENT (wrong paths, wrong shapes):
summary:       () => apiFetch<ListResponse<ModuleSummary>>(`/api/v1/modules`)              // /api/v1/modules doesn't exist
tenantModules: (params) => apiFetch<ListResponse<TenantModuleRow>>(`/api/v1/tenant-modules`)  // path doesn't exist
```

**Gap:** complete rewrite. Both methods point at non-existent paths. Replace with:
- `cards()` → `/api/v1/module-access/modules` returning `ModulesResponse`
- `matrix(params)` → `/api/v1/module-access/matrix` returning `MatrixResponse`

### 5.3 `lib/api/dashboard.ts` (3 methods)

```ts
// CURRENT (placeholders, all wrong paths):
kpis:           () => apiFetch<DashboardKPIs>(`/api/v1/dashboard/kpis`)                    // doesn't exist
topTenants:     () => apiFetch<ListResponse<TopTenantRow>>(`/api/v1/dashboard/top-tenants`)        // doesn't exist
recentActivity: () => apiFetch<ListResponse<RecentActivityRow>>(`/api/v1/dashboard/recent-activity`)  // doesn't exist
```

**Gap:** complete rewrite. Backend has only TWO dashboard endpoints; the placeholder methods anticipated a different shape entirely.
- `kpis()` decomposes into `fleetStats()` + `governanceStats()` — different response types per the cards.
- `topTenants()` and `recentActivity()` have **NO backend equivalent**. Decisions for the consuming page:
  - Drop these sections from `/superadmin/dashboard` UI, OR
  - Keep them rendering against MSW-only fixtures with a "Demo data" treatment (similar to the existing "Stays MSW-only" entries in BUILD_PLAN)
  - **Lean: keep MSW-only for v1 demo; flag for backend prioritization in Phase 5e closeout.**

### 5.4 Other files — no changes anticipated

| File | State | Action |
|---|---|---|
| `lib/api/tenants.ts` | Phase 4b wired | Verify `pnpm gen:types` diff for any tenant aggregate sort keys added in Sanjeev's Step 6.4 work; bundle into 5e.2 if light |
| `lib/api/platform-users.ts`, `tenant-users.ts` | Phase 4d wired | Verify diff |
| `lib/api/org-nodes.ts` | Phase 4e wired | Verify diff |
| `lib/api/lookups.ts` | Phase 4b wired (with `?lists=` envelope) | Verify diff |
| `lib/api/audit-logs.ts`, `guardrails.ts`, `notifications.ts` | MSW-only — no backend equivalent | Stay MSW-only this phase |

---

## 6. JWT / auth contract

### 6.1 No permission_ids required in v0

Per `rbac.md`'s "RBAC enforcement (write-time invariants AI-RBAC-01..06). Not enforced in v0; the catalogue is reference data". The 8 new endpoints accept any authenticated JWT. Visibility is gated by:

- **Audience filter** (app-layer, for `/roles` + `/role_permissions`): TENANT JWTs see TENANT-audience rows only
- **RLS** (DB-layer, via session GUCs `app.tenant_id` / `app.user_type`, for `/module-access/*`, `/dashboard/*`)
- **Reference data, no filter** (for `/permissions`)

**Implication: existing dev persona JWTs (Anjali / Kowalski) work unmodified for the 8 new endpoints.** No `permission_ids` claim updates needed in `lib/auth/personas.ts`.

### 6.2 Persona JWT compatibility

| Persona | userType | hasRealJwt | 8-endpoint compatibility |
|---|---|---|---|
| `anjali` | PLATFORM | ✅ | Full visibility on all 8 endpoints |
| `kira` | PLATFORM | ❌ MSW-only | MSW-only stays MSW-only (no real JWT shipped). Real-backend mode is broken for Kira today; that's a known property, not a regression |
| `kowalski` | TENANT | ✅ | TENANT-scoped visibility per audience filter + RLS |

Existing e2e test `2.8.4` (Anjali on `/superadmin/org`) continues to pass per the persona's PLATFORM JWT having full org-tree visibility.

### 6.3 Future risk (NOT this phase)

When backend ships RBAC write-time enforcement (post-v0), dev personas may need `permission_ids` claims in their JWTs. At that point:
- Re-mint Anjali/Kowalski JWTs with appropriate permission_ids per the catalogue
- e2e test 2.8.4 is the canary (would fail if Anjali's JWT lacks the required permission_id for `/superadmin/org` reads)
- Bundle the JWT update with the write-surface integration chunk that introduces the enforcement

---

## 7. MSW-only frontend pages affected

Pages currently rendering against MSW that flip to real-backend in 5e.2-5e.4 chunks:

| Page | Current state | Flips in chunk | Notes |
|---|---|---|---|
| `/superadmin/roles` | MSW-only (handlers in `mocks/handlers/roles.ts`, fixtures in `mocks/fixtures/roles.json` + `permissions.json`) | 5e.2 | Major UI rework: pre-grouped audience blocks + permission matrix tab |
| `/superadmin/modules` | MSW-only (handlers in `mocks/handlers/modules.ts`) | 5e.3 | Path rewrite + paginated matrix table |
| `/superadmin/dashboard` | MSW-only (handlers in `mocks/handlers/dashboard.ts` — `/kpis`, `/top-tenants`, `/recent-activity`) | 5e.4 | KPI cards rework into 4 fleet + 4 governance card sections; top-tenants + recent-activity stay MSW-only with "Demo data" treatment |

MSW handlers stay as dev-mode fallback (per ambiguity ii) via `MOCK_CONFIG` per-surface flip. Same pattern as Phase 4b/4d.

### 7.1 MSW retirement triggers

Per-surface MSW handler removal (post-Phase-5e) only when:
- Real-backend mode is the default for the surface (no MSW path)
- Local-dev still has MSW available via `NEXT_PUBLIC_USE_MOCKS=true`
- Tests no longer depend on MSW-fixture state (5c.regression e2e harness already uses MSW; flips per-test)

Wholesale MSW removal is out of scope for Phase 5e. Defer to a dedicated cleanup chunk after all surfaces are wired.

---

## 8. OpenAPI snapshot sync method

### 8.1 Provenance header

Per ambiguity viii pushback: `docs/openapi.json` is a verbatim sync from backend repo with provenance metadata embedded in `info.description`:

```json
"info": {
  "title": "Ithina Admin Backend",
  "version": "0.1.0",
  "description": "Synced from ithina-retail-admin-backend@d723b52 docs/endpoints/openapi.json on 2026-05-07. Verbatim copy. Update via: cp ../ithina-retail-admin-backend/docs/endpoints/openapi.json docs/openapi.json && jq <provenance-injection> ..."
}
```

Why `info.description` and not a sibling file:
- Travels with the spec; codegen tools that downstream consume it preserve it
- Visible in any OpenAPI viewer (Swagger UI, Redoc) without leaving the doc
- `openapi-typescript` does NOT strip this field (verified post-sync via `pnpm gen:types`)

### 8.2 Refresh procedure

```bash
# 1. Pull latest backend
cd ../ithina-retail-admin-backend && git pull

# 2. Re-sync the snapshot with provenance injection
COMMIT=$(git -C ../ithina-retail-admin-backend rev-parse --short HEAD)
DATE=$(date -I)
jq --arg commit "$COMMIT" --arg date "$DATE" \
  '.info.description = "Synced from ithina-retail-admin-backend@\($commit) docs/endpoints/openapi.json on \($date). Verbatim copy. Refresh via: see docs/ithina-backend-integration-plan.md §8."' \
  ../ithina-retail-admin-backend/docs/endpoints/openapi.json \
  > docs/openapi.json

# 3. Regenerate TypeScript types
pnpm gen:types

# 4. Diff-review the type changes; rebase any consumer code that breaks
git diff types/openapi-generated.ts
```

The provenance string format is intentionally simple — single line, single mention of the commit short SHA + date. If the format ever needs structured fields (e.g., for a verification CI step), upgrade in place.

---

## 9. Type regen procedure

`pnpm gen:types` runs `openapi-typescript docs/openapi.json -o types/openapi-generated.ts`. Existing Phase 4b/4d pattern.

### 9.1 Per-chunk procedure

Each integration chunk (5e.2 / 5e.3 / 5e.4):

1. **Regenerate** `pnpm gen:types` after the OpenAPI sync (already done in 5e.1). No re-sync needed unless backend HEAD advances.
2. **Re-export** new schemas in `types/api.ts` for hand-maintained consumers. Pattern from Phase 4d:
   ```ts
   export type { components } from "./openapi-generated";
   type schemas = components["schemas"];
   export type RoleListResponse = schemas["RoleListResponse"];
   ```
3. **Update** the placeholder `lib/api/{roles,modules,dashboard}.ts` modules with new signatures.
4. **Update** consuming hooks in `lib/hooks/use-{roles,modules,dashboard}.ts`.
5. **Update** consuming pages with new shape rendering.
6. **Flip** `MOCK_CONFIG[surface] = "real"` (or per-page conditional via existing pattern).
7. **Smoke** locally (`pnpm dev` against deployed backend) + e2e green.

---

## 10. Proposed chunk sequence

### 10.1 5e.2 — RBAC catalog integration (~700-800 LOC)

**Scope:**
- Re-export new schemas from `openapi-generated.ts`: `RoleListResponse`, `AudienceBlock`, `RoleListItem`, `PermissionListResponse`, `PermissionRead`, `RolePermissionsResponse`, `PermissionMatrixResponse`, `PermissionMatrixRow`, `PermissionMatrixRoleColumn`
- Rewrite `lib/api/roles.ts` with new methods (`list`, `permissions`, `getPermissions(roleId)`, `matrix`)
- Update `lib/hooks/use-roles.ts` with the 4 new query hooks
- Update `/superadmin/roles` page UI:
  - List tab: pre-grouped Platform / Tenant audience blocks (was flat)
  - Detail drawer: `RolePermissionsResponse` shape (was `RoleDetail`)
  - Matrix tab: render-ready `PermissionMatrixResponse` (replaces 15-parallel-detail-fetch hack from BUILD_PLAN's "Open question for backend")
- MSW handler updates: align fixtures with new response envelopes; flip `MOCK_CONFIG.roles = "real"` for deployed mode
- e2e: 2-3 tests covering list + matrix rendering against real backend (or MSW with new shape)

**Dependencies:** none (foundational).

**Risk:** UI rework on `/superadmin/roles` may surface design-token gaps; budget includes design-judgment buffer per LOC-discipline.

### 10.2 5e.3 — Module Access integration (~600-700 LOC)

**Scope:**
- Re-export new schemas: `ModulesResponse`, `ModuleCard`, `MatrixResponse`, `MatrixRow`, `MatrixCell`, `ModuleCode`
- Rewrite `lib/api/modules.ts` with new paths + methods
- Update `lib/hooks/use-modules.ts`
- Update `/superadmin/modules` page UI:
  - 6-card grid driven by `/module-access/modules`
  - Tenant × module matrix table driven by `/module-access/matrix` with sort/filter/pagination
  - Position-aligned cell rendering (no key lookup)
- MSW updates + flip
- e2e: 2-3 tests covering cards + matrix + filter narrowing

**Dependencies:** none (independent of RBAC).

**Risk:** position-aligned invariant is easy to break in client-side reorder; e2e test should assert the invariant explicitly.

### 10.3 5e.4 — Dashboard stats integration (~600-700 LOC)

**Scope:**
- Re-export new schemas: `FleetStatsResponse` + 4 cards, `GovernanceStatsResponse` + 4 cards, `DeltaBlock`, `UnavailableReason`
- Rewrite `lib/api/dashboard.ts`:
  - `fleetStats()` + `governanceStats()` (new)
  - `topTenants()` + `recentActivity()` STAY MSW-only with "Demo data" badge — no backend endpoint shipped yet
- Update `lib/hooks/use-dashboard.ts`
- Update `/superadmin/dashboard` page UI:
  - 4 fleet KPI cards (active tenants / platform users / stores / MRR)
  - 4 governance KPI cards with `available: false` "coming soon" treatment for the 3 stubbed cards
  - Top tenants + Recent activity sections with "Demo data" badge (MSW-only)
- MSW updates: split fixtures into fleet-stats + governance-stats shapes; flip `MOCK_CONFIG.dashboard = "real"` for the wired endpoints
- e2e: 2-3 tests covering both PLATFORM (fleet-wide) and TENANT (own-tenant via RLS) projections

**Dependencies:** RBAC catalog (5e.2) provides `governance_stats.custom_roles` semantics — though stubbed. No hard blocker; could land before 5e.2 in principle, but the demo narrative ("dashboard reflects RBAC reality") is stronger after RBAC ships.

**Risk:** `mrr_aggregated.value` is **string with 2 decimal places**, not number — naive `Number(value)` parsing in chart libraries may surprise. e2e test should assert string format.

### 10.4 Per-chunk LOC budget summary

| Chunk | Estimate | Split risk |
|---|---|---|
| 5e.2 RBAC | ~700-800 | At edge — splits possible if matrix UI is heavy |
| 5e.3 Module Access | ~600-700 | Likely single chunk |
| 5e.4 Dashboard | ~600-700 | Likely single chunk |

Each chunk re-applies the 850+ split-discipline rule at plan time per the existing memory.

---

## 11. Known risks

| Risk | Mitigation |
|---|---|
| `pnpm gen:types` regeneration after OpenAPI sync may surface unexpected breaking changes in shared paths (tenants / users / org-tree) | Run `pnpm gen:types` immediately after sync (this chunk); tsc errors surface diff; bundle hotfix into 5e.2 if light, otherwise stand up 5e.1-hotfix |
| Anjali/Kowalski JWT validity (e.g., expired) | Out of scope for this chunk (no real-backend calls). 5e.2 first action verifies JWT validity via `/health` + `/permissions` curl probe |
| `top-tenants` + `recent-activity` MSW-only sections look weird in real-backend mode | "Demo data" badge treatment in 5e.4; flag backend prioritization in Phase 5e closeout |
| Future RBAC permission_ids enforcement on dev JWTs | Tracked in §6.3; canary is e2e 2.8.4; bundle JWT update with the write-surface integration chunk |
| Aggregate sort keys on `/tenants` (Step 6.4) may have shipped breaking changes | Verify in 5e.2 prep via `pnpm gen:types` diff on `TenantListParams` and related types |

---

## 12. Cross-references

- Backend per-endpoint docs: `ithina-retail-admin-backend/docs/endpoints/{rbac,module-access,dashboard,tenants,platform-users,tenant-users,org-tree}.md`
- Frontend handoff doc: `docs/frontend-backend-wiring-handoff.md` (forward-looking; supplements this current-state plan)
- BUILD_PLAN Phase 4b "Stays MSW-only" entries: catalogue of MSW-only surfaces predating this plan
- Memory `feedback_loc_split_discipline.md`: 850+ LOC trigger applies to each 5e.2-N chunk
