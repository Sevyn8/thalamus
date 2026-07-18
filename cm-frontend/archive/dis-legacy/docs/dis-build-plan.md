# DIS Frontend Phased Build Plan

**Status:** Draft v1
**Scope:** v1 surface from `docs/dis-surface-map.md`
**Owner:** Frontend planning
**Companion to:** `docs/dis-surface-map.md`, `BUILD_PLAN.md`
**Backend status at time of writing:** DIS backend build not started; frontend builds against MSW-only and migrates surfaces to real-backend as Sanjeev's endpoints land.

---

## Operating principles

Same discipline that ran Phases 4b, 4d, 4e:

1. Chunks are scoped to land in a single Claude Code session, with explicit stop points and approval gates between chunks.
2. Each chunk produces a real commit with `pnpm tsc --noEmit` clean and `pnpm lint` at baseline (no new errors).
3. Smoke is local-first (MSW), then deploy + browser smoke when real-backend is involved.
4. CORS preflights verified via curl before any real-backend smoke claim.
5. `pgrep -f "next dev"` before any background `pnpm dev`.
6. MSW smoke steps never assume RLS scoping; RLS verified against real backend only.
7. BUILD_PLAN.md updated at every chunk close with hash, deploy revision, smoke result, and any new Known-deferred entries.

Phase numbering: starts at **Phase 5** (4b/4d/4e wrapped Ithina wiring; DIS is a new arc).

---

## Phase ordering rationale

Three layers of work, ordered by dependency:

**Layer A: Chrome refactor.** Touches every Ithina page. Must land first, in tiny no-op-shaped commits, before any DIS code arrives. Risk: regression on working Ithina deployment. Mitigation: each chunk visibly identical to the previous deploy until DIS routes light up.

**Layer B: DIS shell + foundation.** Routes, navigation, MSW scaffolding, design-system reuse audit. No real features yet. Establishes structure DIS pages plug into.

**Layer C: DIS feature pages.** v1 page-by-page wiring against MSW. Uploads (LLM-mapping review) first since it is the highest-leverage v1 screen. Other pages follow in priority order.

**Layer D: Real-backend migration.** Triggers when Sanjeev ships endpoints. Each surface migrates from MSW to real backend in a chunk that mirrors Phase 4 wiring discipline (types regen, API client, hooks, smoke).

Layers A and B are sequential. Layer C pages can parallelize once B lands but should not actually parallelize in early chunks; serial execution surfaces shared-component reuse that benefits later chunks. Layer D interleaves with C as Sanjeev's deploys land.

---

## Phase 5a: Chrome refactor (Layer A, pre-DIS)

Goal: prepare `admin-frontend` chrome to host a second product without breaking Ithina. Zero new user-visible features. Each chunk verifiable by "Ithina smoke at deployed URL still passes."

### Chunk 5a.1: Sidebar accepts nav items as props (no-op refactor)

Refactor `Sidebar.tsx` so its nav structure (sections, items, icons, route paths) is provided by props, with the current Ithina nav extracted to a constant `ithinaSidebarNavItems` and passed in from the layout. Visual output identical.

Acceptance:
- `pnpm tsc --noEmit` clean
- `pnpm lint` at baseline
- `pnpm build` clean
- Manual local smoke: every Ithina page renders identically (Tenants, Org Tree, Users, Dashboard, Roles, Audit, Modules, Guardrails)
- Deploy and re-run prior Phase 4e smoke checklist against deployed URL: tenants list loads, org-tree lazy-load fires, RLS scopes Kowalski

Stop point. No further work until smoke confirms zero regression.

Risk: Sidebar is rendered on every authenticated page. Any prop misnaming or import path miss breaks every page.

### Chunk 5a.2: Product-switcher component, feature-flagged

Add `ProductSwitcher.tsx` component to the header area, replacing the static "Ithina · Superadmin Governance Console" text with a dropdown trigger. v1 dropdown contains a single non-interactive "Ithina Console" entry until `NEXT_PUBLIC_DIS_ENABLED=true`. Component imports from `lib/products.ts` registry (initially Ithina-only).

Behind the flag (when enabled): dropdown lists Ithina + DIS, each linking to its respective dashboard.

Acceptance:
- Flag off (production default): visually identical to current header
- Flag on (local dev): dropdown renders both entries, clicking DIS navigates to `/dis/dashboard` (which is a 404 in this chunk, expected)
- `pnpm tsc --noEmit` clean
- `pnpm lint` at baseline

Stop point.

### Chunk 5a.3: Auth and proxy audit

Audit `proxy.ts`, `next.config.js` rewrites, auth middleware path matching, and `from=` redirect logic for assumptions that the only protected namespace is `/superadmin`. Document findings and fix any hard-coded path patterns to handle `/dis/*` once it exists. Add `/ithina/*` -> `/superadmin/*` redirect as a future-proofing hedge (cheap insurance, not load-bearing).

Acceptance:
- Document audit findings inline in `proxy.ts` and `middleware.ts` comments
- All Ithina routes still protected, still redirect to `/dev/login` when unauth, still preserve `from=` correctly
- `/dis/*` paths return 404 in this chunk (no routes yet) but are recognized by middleware as protected, not bypassed
- Unauth `/dis/anything` redirects to `/dev/login` with `from=/dis/anything`

Stop point. Phase 5a complete. No DIS code yet; all Ithina behavior preserved.

---

## Phase 5b: DIS shell and foundation (Layer B)

Goal: scaffold `/dis/*` route tree, second API client, second OpenAPI pipeline, second MSW handler tree, second sidebar variant. No real DIS pages yet beyond a shell dashboard. Sets the stage for Layer C.

### Chunk 5b.1: DIS sidebar nav constant and route shell

Create `lib/dis/sidebar-nav-items.ts` containing the DIS sidebar structure from the surface map (OVERVIEW / INGESTION / QUALITY / GOVERNANCE / INSIGHTS / HELP, with ADMIN section conditional on persona). All route paths point to placeholder pages.

Create `app/(authenticated)/dis/layout.tsx` rendering the same chrome as Ithina but passing DIS sidebar nav items to the shared Sidebar component. Persona detection from JWT determines whether ADMIN section renders.

Create placeholder pages for every v1 route in the surface map (`app/(authenticated)/dis/*/page.tsx`), each rendering an `<UnderConstruction>` component with the route name. Routes resolve, navigation works, no real content yet.

Update `lib/products.ts` registry: DIS is now a real entry. Product-switcher dropdown (still flag-gated) routes to `/dis/dashboard` which renders the placeholder.

Acceptance:
- `pnpm tsc --noEmit` clean
- All v1 routes from surface map exist and render placeholder
- Persona switch (Anjali vs Kowalski) shows / hides ADMIN section correctly
- `pnpm lint` at baseline

Stop point.

### Chunk 5b.2: DIS API client scaffolding

Create `lib/dis/api-client.ts` mirroring Ithina's API client pattern but pointed at a DIS backend URL (env var `NEXT_PUBLIC_DIS_API_BASE`, undefined for now since no backend exists). Client carries the same JWT as Ithina's client.

Create `types/dis-openapi-generated.ts` placeholder file. Set up `gen:dis-types` script in package.json mirroring Ithina's `gen:types`, pointed at `docs/dis-openapi.json` (file does not exist yet; script tolerates missing source with a warning, generates empty type file). When Sanjeev ships a spec, dropping it at that path and re-running the script populates the file.

Create `mocks/dis/handlers/index.ts` and `mocks/dis/fixtures/` directory. Wire the DIS handler tree into the existing MSW worker.

Acceptance:
- `pnpm gen:dis-types` runs without error (warns about missing spec, generates empty types)
- `pnpm tsc --noEmit` clean (placeholder types are valid TS)
- MSW worker initializes both Ithina and DIS handler trees in dev
- `pnpm build` clean
- `pnpm lint` at baseline

Stop point.

### Chunk 5b.3: Shared component reuse audit and extraction

Inventory components that DIS will reuse from Ithina, identify any hard-coded to Ithina semantics, and refactor for genericity. Candidates from the surface map:

- Org-node picker (DIS source create/edit wizard)
- Tenant filter dropdown (DIS admin views)
- Persona-scoped data tables (DIS sources list, runs list, etc.)
- Detail drawer pattern (DIS source detail, run detail, upload detail)
- Status chip / health badge primitives
- Empty-state and error-inline components
- Pagination / search / filter primitives

For each: confirm location, confirm it accepts props (not Ithina-hardcoded), or refactor in place to do so. No new components in this chunk; only un-coupling existing ones.

Acceptance:
- Document each shared component's location and reuse readiness in `docs/dis-shared-components.md`
- Any in-place refactors keep Ithina behavior identical (smoke against deployed URL)
- `pnpm tsc --noEmit` clean
- `pnpm lint` at baseline

Stop point. Phase 5b complete. DIS shell exists; Layer C can begin.

---

## Phase 5c: DIS v1 feature pages (Layer C, MSW-only)

Goal: build v1 page set against MSW. Each page chunk produces a working page with mocked data, local-smoke-passable. Deploy happens at the end of each chunk for browser smoke against deployed (still MSW-mode in DIS frontend until backend ships).

Order is deliberate. Highest-leverage page first (uploads + LLM mapping review), then operational core (sources, runs), then quality and governance, then admin views, then onboarding wizard last because it integrates everything.

### Chunk 5c.1: Uploads and LLM mapping review

The flagship v1 screen per the surface map. Build first.

Pages: `/dis/uploads` (list + new upload), `/dis/uploads/[id]` (LLM mapping review).

Components: file upload area, LLM mapping confidence display per column, manual-mapping fallback path, sample-row table with PII redaction (heuristic + canonical-schema-tag), `dis.pii.view` gated raw-view affordance with audit-log call, validation results panel, ingest action.

MSW handlers: `/api/v1/uploads` list, `/api/v1/uploads` POST, `/api/v1/uploads/{id}` GET, `/api/v1/uploads/{id}/mapping` PATCH, `/api/v1/uploads/{id}/confirm` POST.

Fixtures: 3-5 sample uploads in different states (pending review, confirmed, failed validation, mid-ingest). Sample CSVs with realistic POS / inventory / supplier columns to exercise LLM mapping confidence visualization.

LLM-assist toggle: hierarchy logic implemented (Ithina Module Access capability + DIS tenant opt-in, both must be true for LLM proposals to render). MSW returns "both on" by default; tenant opt-in toggle accessible via DIS settings page (built minimally in this chunk if needed).

Acceptance:
- Local smoke: upload list, click upload, mapping review renders, manual override works, confirm action commits
- `dis.pii.view` permission gating works (default redacted, click "View raw" reveals)
- LLM-assist off path renders manual-mapping flow correctly (toggle either layer off, retry)
- `pnpm tsc --noEmit` clean
- `pnpm lint` at baseline

Stop point. Long chunk; possibly split into 5c.1a (page shell + list) and 5c.1b (mapping review + redaction) if scope grows.

### Chunk 5c.2: Sources and source create wizard

Pages: `/dis/sources`, `/dis/sources/new`, `/dis/sources/[id]`, `/dis/sources/[id]/edit`, `/dis/sources/[id]/runs`.

Components: source list with type / status / health filters, source create wizard (5 steps: type / config / test / org-node / schedule), source detail with tabs for config / runs / validation / freshness, source edit form.

Org-node picker: reuses Ithina's org-tree component (Phase 4e). Single `org_node_id` per source per the resolution.

MSW handlers and fixtures cover 6-8 sources across types (CSV, POS API, ERP API, FTP).

Acceptance:
- Source list filters work, wizard creates a source, detail tabs load, edit saves
- Org-node picker shows tenant's tree (mocked), single-select enforced
- `pnpm tsc --noEmit` clean

Stop point.

### Chunk 5c.3: Runs and run detail

Pages: `/dis/runs`, `/dis/runs/[id]`, `/dis/runs/active`, `/dis/runs/failed`.

Components: run history table, run detail with log tail / DAG view / downstream-effects, retry / cancel / acknowledge actions, polling for active runs.

MSW: 30-50 runs across sources, mix of success/failure/in-progress states.

Acceptance: filter, drill into run, retry / cancel / ack actions update MSW state, polling refreshes active list.

Stop point.

### Chunk 5c.4: Validation, drift, freshness

Pages: `/dis/validation`, `/dis/validation/rules/[id]`, `/dis/validation/drift`, `/dis/validation/drift/[id]`, `/dis/freshness`, `/dis/freshness/breaches`.

Components: rule registry, rule editor, drift inbox with LLM-proposed-interpretation (gated on LLM-assist hierarchy), drift detail with accept/reject/rename, freshness widgets per source, SLA editor, breach incident list.

Acceptance: rules CRUD, drift events accept / reject / rename, SLA edit, breach list filterable.

Stop point.

### Chunk 5c.5: Alerts and channels

Pages: `/dis/alerts`, `/dis/alerts/[id]`, `/dis/alerts/rules`, `/dis/alerts/rules/[id]`, `/dis/alerts/channels`.

Components: alert inbox with ack/resolve/snooze, rule editor, channel config (email / Slack / PagerDuty / webhook), test-channel action.

Acceptance: alert lifecycle works, rule CRUD, channel test triggers MSW success/failure.

Stop point.

### Chunk 5c.6: Backfills and templates

Pages: `/dis/backfills`, `/dis/backfills/[id]`, `/dis/templates`, `/dis/templates/new`, `/dis/templates/[id]`, `/dis/templates/[id]/edit`.

Components: backfill create form with date range and dry-run, backfill progress display, template list with version chip and pending-migration count, template create wizard (LLM-proposed or manual fallback), template detail with diff-against-latest when behind, template edit.

Inheritance logic: hybrid policy implemented. Templates carry a pinned canonical schema version. MSW simulates a canonical-schema bump scenario so the migration prompt UI can be smoked.

Acceptance: backfill create / cancel works, template CRUD works, version chip shows correct state, migration prompt renders when MSW fixture has pending-breaking-change.

Stop point.

### Chunk 5c.7: Canonical schema and dashboard

Pages: `/dis/canonical-schema`, `/dis/canonical-schema/[domain]`, `/dis/canonical-schema/[domain]/[entity]`, `/dis/canonical-schema/coverage`, `/dis/dashboard`, `/dis/dashboards` (single ingestion-health dashboard for v1).

Components: canonical browser (read-only for tenants), coverage gap analysis, dashboard widgets (ingest health summary, recent runs, active alerts, freshness scorecard, cost-this-period).

Acceptance: canonical browse works, coverage gaps render, dashboard widgets populate from MSW data, drill-through links work.

Stop point.

### Chunk 5c.8: Cost, admin views, onboarding, help

Final feature batch.

Pages: `/dis/cost`, `/dis/cost/budgets`, `/dis/admin/fleet`, `/dis/admin/provisioning`, `/dis/admin/llm-ops`, `/dis/admin/canonical-schema`, `/dis/onboarding`, `/dis/docs`, `/dis/status`, `/dis/changelog`.

Components: cost overview with allowance + consumption + projected overage (default unlimited per resolution), budget editor, fleet health matrix (admin), provisioning state per tenant (admin), LLM ops with prompt registry and confidence thresholds and per-tenant capability toggle (admin), canonical schema write side with breaking-vs-additive classifier (admin), onboarding wizard (first-time DIS user end-to-end flow that integrates upload + template + source + first ingest).

Acceptance: cost UI renders allowance state, budget edit, admin pages persona-gated, LLM ops can edit prompts and thresholds in MSW, canonical schema admin can version-bump with breaking-flag, onboarding wizard runs end-to-end.

Stop point. Phase 5c v1 feature surface complete (against MSW).

### Chunk 5c.9: Phase 5c closeout and deploy

Deploy the full DIS frontend to the dev environment with `NEXT_PUBLIC_DIS_ENABLED=true`. Browser smoke at deployed URL covers:

- Anjali persona: product-switcher visible, switches to DIS, every v1 page renders, admin section visible
- Kowalski persona: product-switcher visible if Module Access (mocked) has DIS enabled, switches to DIS, every v1 page renders, admin section hidden
- All flows local-smoke-passable now passable on deployed URL

BUILD_PLAN updated with Phase 5c closeout, all chunk hashes, deploy revision, MSW-mode-known-deferred items.

Stop point. Phase 5c shipped.

---

## Phase 5d: Real-backend migration (Layer D)

Triggers when Sanjeev ships DIS backend endpoints. Each migration is a chunk mirroring Phase 4d / 4e discipline.

Order driven by Sanjeev's deploy order, but recommended priority if he asks:

1. **Sources read** + **runs read** (highest user-visible value, smallest schemas)
2. **Uploads + mapping write** (needed to get real data flowing; depends on backend LLM integration)
3. **Validation + drift reads**
4. **Templates CRUD**
5. **Canonical schema reads** (likely first available since Sanjeev built the schemas already)
6. **Freshness, alerts, backfills**
7. **Admin endpoints** (fleet, provisioning, LLM ops)
8. **Cost endpoints**
9. **Dashboard composites**

Each migration chunk:
- Drop DIS OpenAPI snapshot at `docs/dis-openapi.json` (or fetch live URL once Sanjeev confirms path conventions)
- Run `pnpm gen:dis-types` to regenerate types
- Curl preflight verification on new paths from deployed frontend origin
- Replace MSW handlers for that surface with real-backend calls (keep MSW handlers as contract twins per Phase 4 discipline)
- Local smoke (against MSW) + deploy + browser smoke (against real backend)
- BUILD_PLAN closeout

Migration chunks are independently scoped; one surface migrating does not require others to be ready. MSW remains the fallback for unbuilt endpoints.

---

## Phase 5e: Production cutover blockers

Three Ithina dependencies must be real-backend before DIS goes to actual production tenants (not just dev / staging):

1. **Module Access wired.** Without it, every tenant sees DIS regardless of license.
2. **Roles & Permissions wired with module-namespaced catalog.** Without it, DIS sub-features cannot be permission-gated; `dis.pii.view` and similar are unenforced.
3. **Audit log reads wired.** DIS publishes events but no one can view them.

These are Ithina-side work, not DIS-side. Track in this build plan only as cutover gates; build happens in separate Ithina phases when Sanjeev ships those endpoints.

DIS frontend can ship to dev / staging / internal demo without these. Production cutover for paying tenants requires all three.

---

## Estimated chunk counts and timing

- Phase 5a: 3 chunks (chrome refactor)
- Phase 5b: 3 chunks (DIS foundation)
- Phase 5c: 9 chunks (v1 feature pages, including closeout deploy)
- Phase 5d: ~9 migration chunks, each per surface, triggered by Sanjeev's deploys
- Phase 5e: tracked, executed under separate Ithina phases

Total: ~24 chunks across the arc. Phases 5a + 5b + 5c are 15 chunks of frontend-only work, executable now without backend dependency.

Cadence assumption: 1-2 chunks per Claude Code session if scope discipline holds. At your historical pace (Phase 4d ran 3 chunks across multiple sessions over a day), Phase 5a-c is realistic in 2-3 weeks of active work.

---

## Risks and mitigations

1. **Sidebar refactor regresses Ithina pages.** Highest risk in the plan because Sidebar is rendered everywhere. Mitigation: 5a.1 is no-op-shaped, deploys independently, smoke-passes against current Ithina checklist before any further work.

2. **DIS shell pages drift from surface map.** Easy to forget a v1 route or build something not in the map. Mitigation: chunk 5b.1 explicitly creates a placeholder for every v1 route; later chunks fill them in. Surface map is canonical.

3. **MSW fixtures balloon and become unmaintainable.** Each Layer C chunk adds fixtures. Mitigation: scope fixtures to "just enough to smoke the chunk." Resist building a full MSW universe. Most Phase 4d / 4e MSW fixtures stayed small for this reason.

4. **LLM-assist UI gets bolted on instead of designed in.** Easy to build the LLM-on path first and stub LLM-off. Mitigation: 5c.1 acceptance explicitly requires both paths working. Manual-mapping is a first-class fallback, not a stub.

5. **Real-backend migration in 5d outpaces tests.** Phase 4 history shows a real-backend smoke catches things MSW does not. Mitigation: every migration chunk includes deploy + real-backend browser smoke before close, never declares done on local-MSW pass alone.

6. **Cross-product surfaces (Audit, Module Access, Roles) drag DIS down.** DIS depends on Ithina surfaces still being MSW-only. Mitigation: design DIS v1 to function with MSW Ithina dependencies; production cutover gated on Phase 5e but development can proceed.

7. **Bundle size grows from DIS additions.** Single Next.js app means DIS code ships in Ithina bundles unless route-split. Mitigation: rely on Next.js automatic per-route code splitting, monitor bundle sizes at each chunk close, escalate to dynamic imports if a route exceeds a threshold (suggest 500 kB initial JS as the trigger).

---

## How to start

First Claude Code session: hand it `docs/dis-surface-map.md`, `docs/dis-build-plan.md` (this file), and `BUILD_PLAN.md`. Ask for Phase 5a Chunk 5a.1 only. Approve the chunk plan it produces before any code lands. Same discipline as Phases 4b / 4d / 4e.

Do not start with DIS feature work. Layer A first.

---

## Stop conditions (Claude Code should stop and ask if any of these trigger)

1. A chunk grows beyond ~600 lines of diff. Re-scope.
2. A chunk requires a backend mutation that does not exist. Stop, document, defer to Phase 5d / 5e.
3. A shared component refactor breaks an Ithina page. Stop, restore, scope a separate Ithina-side fix chunk.
4. Sanjeev ships a DIS backend endpoint mid-Phase-5c. Pause feature work and decide whether to migrate that surface immediately (5d insertion) or finish the current 5c chunk first.
5. Bundle size for any DIS route exceeds 500 kB initial JS. Stop, scope a dynamic-import refactor.
6. CORS preflight fails on any deploy smoke. Stop, do not declare success based on deploy alone.
