# Step 4.1 — Provision Tenant Anchor Flow

## Context and intent

v0 shell is complete (14/14 steps committed). Every page-level CTA toasts "Coming in v1" because the build was deliberately read-only. This step builds **one** end-to-end write flow as a pattern reference for future write flows.

The flow chosen: **Provision Tenant** via modal form on the Tenants page. Reasons:

- Tenant creation is the highest-frequency operational write (every new pilot customer triggers it)
- It's a clean composition: form fields → POST → optimistic insert → drawer-open of created tenant
- It exercises every pattern future flows will need: form composition, Zod validation, server validation surface, optimistic update with rollback, audit log entry generation, post-success navigation
- It's the only write flow whose success state has a natural follow-up (review what you just created)

This is purely an MSW-mocked flow. Sanjeev's backend does not have write endpoints yet. When backend writes land, wiring is a config flip plus a small contract reconciliation. Don't over-design for the eventual real contract.

## Source of truth for field shape

The form mirrors what the backend will eventually accept on `POST /v1/tenants`. Sources triangulated:

- **`Ithina_postgres_SQL_DDL_tenants_v3.sql`** (DDL) — column names, lengths, regex constraints, nullability
- **`tenants-api-contract-v0.md` section 4.4** — POST request body shape, required fields, error codes
- **`Ithina_Admin_Frontend.md` section 7.2.4** — Lovable workflow spec for field UX (which fields appear, defaults, side effects)
- **Sanjeev's deployed OpenAPI `TenantsListItem`** — response shape returned on 201

Where these sources disagree, DDL + OpenAPI win on field shape; Lovable spec wins on UX (which fields, defaults, modal copy).

## Acceptance criteria

1. Tenants page "+ Provision tenant" CTA opens a `<ProvisionTenantModal />` instead of toasting v1.
2. Modal title "Provision new tenant", subtitle "Create a client organization with module access."
3. Modal has the field set listed in section "Form scope" below; validation rules in "Validation".
4. Submit button shows loading state while POST is in flight (artificial 400-700ms delay in MSW).
5. On 201 success: modal closes, optimistic placeholder card is replaced with real card, navigate to `/superadmin/tenants?tenant=<new_id>` to auto-open the created tenant's drawer, success toast `Tenant <name> provisioned`.
6. On 400 VALIDATION_ERROR: form-level error rendered at top of form, field-level errors rendered inline; modal stays open; no list mutation.
7. On 409 DISPLAY_CODE_TAKEN (display_code collision case-insensitive): inline error on display_code field "Display code is already in use"; modal stays open.
8. On 500 INTERNAL_ERROR: optimistic placeholder is rolled back from list; toast "Could not provision tenant. Please try again."; modal stays open with form values preserved.
9. New tenant appears in subsequent `GET /v1/tenants` calls (MSW handler maintains in-memory state across requests for this session).
10. New audit log entry generated and visible on `/superadmin/audit` after tenant creation.
11. `NEXT_PUBLIC_SIMULATE_ERRORS=true` env var makes 1-in-5 POSTs return 500 (rollback path is exerciseable in smoke).
12. `pnpm tsc --noEmit` exits zero.
13. `pnpm lint` exits zero.
14. `pnpm build` succeeds (production build sanity check; v0 hasn't run this yet).
15. No console errors during the full flow (modulo the cold-load activation race which is Phase 5c-deferred — pre-mark this as ⚠️).
16. BUILD_PLAN.md updated: Step 4.1 → DONE; Phase 4a entry added; Phase 4b/4c deferred sections updated; Phase 5a/5b/5c reflecting current direction.

## Form scope

Mirrors the Lovable spec section 7.2.4 field list, with field names and constraints drawn from the DDL. Backend POST contract requires only `name` and `region`; the rest are optional at the API level but the form makes most of them required for good demo UX.

**Required fields:**
- **Tenant name** → `name` (text, 1-200 chars). Required by DDL `ck_tenants_name_length`.
- **Region** → `region` (select: `US` | `EU`, default `US`). Required by DDL `NOT NULL`.
- **Tier** → `tier` (select: `ENTERPRISE` | `MID_MARKET` | `SMB` | `SINGLE_STORE`, default `SMB` per Lovable spec). DDL allows null but Lovable requires for UX.
- **Industry** → `industry` (select: `CONVENIENCE_FUEL` | `CONVENIENCE` | `GROCERY` | `HYPERMART` | `SPECIALITY_GROCERY` | `ORGANIC_GROCERY`, no default). DDL allows null but Lovable requires.
- **Country** → `country` (text, 2-100 chars). DDL allows null but Lovable requires.
- **Primary contact** → `primary_contact_name` (text, 1-200 chars). DDL allows null but Lovable requires.
- **Contact email** → `contact_email` (email, lowercased on submit). DDL allows null but Lovable requires.
- **Stores** → `number_of_stores` (integer, default 1, min 1). When provided, also send `number_of_stores_as_of_date` set to today (DDL pairs them via `ck_tenants_number_of_stores_as_of_consistency`).

**Optional fields:**
- **Display code** → `display_code` (text, optional, lowercase regex `^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$`, 3-64 chars). DDL nullable; help text "Auto-generated from name if blank — short URL-friendly identifier (e.g., 'acme-retail')". When user types name, optionally show preview of auto-generated slug.
- **Monthly revenue (USD)** → `monthly_revenue_usd` (numeric string, optional, >= 0). When provided, also send `monthly_revenue_as_of_date` set to today (DDL pairs them via `ck_tenants_monthly_revenue_as_of_consistency`). Format input as decimal string with 2 places.

**Server-defaulted (do not appear on form):**
- `id` — UUID v7 generated server-side (MSW: `crypto.randomUUID()` is fine for v0 mocks)
- `status` — defaults to `ONBOARDING`
- `created_at`, `updated_at` — server timestamps
- `num_users` (or whatever v0 fixtures call it; see section "MSW response field names" below) — 0
- `modules` — empty array initially (backend doesn't have `tenant_module_access` table yet; modules can't be set at creation)

**Explicitly NOT in the form (deferred to v1):**
- Modules-enabled multi-checkbox (Lovable has this; deferred — backend doesn't model `tenant_module_access` yet)
- Initial owner email/invite (Lovable flags this as open question; v1 surface)
- Status select Trial/Active (Lovable has this; backend always defaults to ONBOARDING; status changes via separate suspend/resume flows)
- `legal_name` (appears in contract POST example but not in OpenAPI list shape; safe to omit)

## Validation

Use **React Hook Form + Zod**. Schema lives at `lib/schemas/provision-tenant.ts`.

Field-level rules:
- `name`: required, trim, 1-200 chars, no leading/trailing whitespace after trim
- `display_code`: optional, trim, lowercase, 3-64 chars, regex `^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$`. Auto-lowercase on blur (don't reject mixed case in form; transform).
- `region`: required, must be `US` or `EU`, defaults to `US`
- `tier`: required, must be one of the four enum values, defaults to `SMB`
- `industry`: required, must be one of the six enum values, no default
- `country`: required, trim, 2-100 chars
- `primary_contact_name`: required, trim, 1-200 chars
- `contact_email`: required, valid email format, lowercased on submit (DDL `ck_tenants_contact_email_lowercase` requires it)
- `number_of_stores`: required, integer >= 1, default 1
- `monthly_revenue_usd`: optional, when provided must be a valid decimal string >= 0 (e.g., "500.00")

Field-level errors render inline below each field on blur or on submit attempt. Form-level errors (server-returned) render in a banner at the top of the form.

Don't go overboard with deeper validation. No country code validation, no business-logic validation (e.g., "tier ENTERPRISE requires monthly_revenue > 0"). Keep the form buildable in 1.5 days.

## Enum sources (use existing v0 lookups fixture)

v0 already has `mocks/fixtures/lookups.json` with the canonical enum vocab populated by Step 1.3. The form's tier / industry / region selects must consume this via `useLookups()` rather than hardcoding enum lists. This is the contract pattern (per `tenants-api-contract-v0.md` section 4.9 — "the one place backend ships display labels"); hardcoding parallel lists in the form would drift.

If `mocks/fixtures/lookups.json` is missing any of these lists (industries, tiers, regions, statuses), update the fixture to include them with the canonical enum codes and display labels. The label values for industries should match the contract's lookups example: `"CONVENIENCE_FUEL" → "Convenience / Fuel"`, `"HYPERMART" → "Hypermarket"`, `"SPECIALITY_GROCERY" → "Specialty Grocery"`, `"ORGANIC_GROCERY" → "Organic Grocery"`, `"CONVENIENCE" → "Convenience"`, `"GROCERY" → "Grocery"`.

## MSW handler shape

New file: `mocks/handlers/tenants-write.ts` (or extend existing `mocks/handlers/tenants.ts`).

POST `/v1/tenants` handler behavior:

1. Parse JSON body. If invalid JSON → 400 `{code: "INVALID_JSON", message: "...", request_id: "..."}`
2. Validate against expected shape (required fields present, enums valid, formats correct, paired as_of_dates consistent). If invalid → 400 `{code: "VALIDATION_ERROR", message: "...", details: {field_errors: {field_name: ["error message"]}}, request_id: "..."}`
3. Check display_code collision against current in-memory state (case-insensitive, only if display_code provided). If collides → 409 `{code: "DISPLAY_CODE_TAKEN", message: "Display code is already in use", details: {field: "display_code"}, request_id: "..."}`
4. Generate UUID for new tenant id (use `crypto.randomUUID()` — v0 doesn't need real UUID v7)
5. If display_code blank, auto-generate from name: lowercase, replace whitespace and special chars with hyphens, collapse consecutive hyphens, trim leading/trailing hyphens. Example: "Acme Foods Inc." → "acme-foods-inc". Verify it matches the regex; if not, fall back to `tenant-<8-char-uuid-prefix>`.
6. Construct full tenant resource shape per the existing v0 `Tenant` type (so MSW response slots into existing list/detail handlers without breaking smoke):
   - All required fields populated
   - `status: "ONBOARDING"`
   - `num_stores`: copy from `number_of_stores` (or 0 if missing) — this is the live count column
   - `num_users`: 0 (no users yet) — match v0 fixture field name; see "MSW response field names" below
   - `modules: []`
   - `created_at`, `updated_at`: current ISO timestamp
7. Append to in-memory tenants list
8. Append an audit log entry to in-memory audit list: `{id, occurred_at: now, actor: <current persona shape>, tenant_id: <new tenant id>, tenant_name: <new tenant name>, action: "Created tenant", resource: "<tenant name> (<status>)", scope: "GLOBAL", result: "SUCCESS", ip_address: "127.0.0.1"}`. Match the existing audit-logs fixture shape.
9. If `NEXT_PUBLIC_SIMULATE_ERRORS=true` AND `Math.random() < 0.2`: skip 5-8, return 500 `{code: "INTERNAL_ERROR", message: "Service temporarily unavailable", request_id: "..."}`
10. Otherwise: 201 with the full created tenant resource as response body
11. Add artificial latency: `await new Promise(r => setTimeout(r, 400 + Math.random() * 300))`

**MSW response field names: confirm before building.** v0 type defined at Step 1.3 uses `num_users`. Sanjeev's deployed OpenAPI uses `num_users_active`. There's existing drift. **Use whatever the v0 fixtures and `types/api.ts` currently use** — don't introduce a second drift point. The rename happens later as part of wiring (mechanical find/replace). If you spot the drift while building this step, note it in the final report; don't fix it here.

**In-memory state pattern.** The handler module needs a mutable copy of the tenants fixture that persists across requests within a session:

```ts
// mocks/handlers/tenants-store.ts
import tenantsFixture from "@/mocks/fixtures/tenants.json";

let tenantsState = structuredClone(tenantsFixture);

export const getTenants = () => tenantsState;
export const addTenant = (tenant) => { tenantsState = [...tenantsState, tenant]; };
export const findByDisplayCode = (code) =>
  tenantsState.find(t => t.display_code?.toLowerCase() === code.toLowerCase());
```

GET handlers (existing) need to be updated to read from `getTenants()` instead of importing the fixture directly. Same pattern for audit-logs (since each create generates one audit entry).

Server reload (dev server restart) resets state — that's expected and fine for v0.

## Optimistic update + rollback

Use TanStack Query's `useMutation` with `onMutate` / `onSuccess` / `onError`.

```ts
useMutation({
  mutationFn: provisionTenant,
  onMutate: async (newTenant) => {
    await queryClient.cancelQueries(["tenants"]);
    const previous = queryClient.getQueryData(["tenants"]);
    const optimisticTenant = {
      id: `temp_${crypto.randomUUID()}`,
      status: "ONBOARDING",
      num_stores: newTenant.number_of_stores ?? 0,
      num_users: 0,
      monthly_revenue_usd: newTenant.monthly_revenue_usd ?? null,
      modules: [],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      ...newTenant,
    };
    queryClient.setQueryData(["tenants"], (old) => ({
      ...old,
      items: [optimisticTenant, ...old.items],
    }));
    return { previous, optimisticTenant };
  },
  onError: (err, newTenant, context) => {
    queryClient.setQueryData(["tenants"], context.previous);
    // surface error in form (400/409) or toast (500)
  },
  onSuccess: (createdTenant, newTenant, context) => {
    queryClient.invalidateQueries(["tenants"]);
    queryClient.invalidateQueries(["tenant-stats"]);
    queryClient.invalidateQueries(["audit-logs"]);
    toast.success(`Tenant ${createdTenant.name} provisioned`);
    router.replace(`/superadmin/tenants?tenant=${createdTenant.id}`);
  },
})
```

**Temporary id.** Optimistic placeholder uses `temp_<uuid>` for id. On success, real id replaces it via query invalidation. On error, the placeholder is rolled out by restoring previous query data.

**Rollback discipline.** The `onError` rollback restores ALL prior tenant list state, not just the optimistic insert. This is correct — TanStack Query's pattern. Don't try to surgically remove just the optimistic entry.

**Idempotency-Key (forward-compatible).** Per `tenants-api-contract-v0.md`, the eventual real backend will accept an `Idempotency-Key: <uuid>` header for double-submit prevention. Wire the API client to send a fresh UUID per `provisionTenant` call now (cheap, prevents future rework). MSW handler can ignore it for v0; just receive it.

## Files added or modified

New:
- `components/tenants/ProvisionTenantModal.tsx` — the modal form component
- `lib/schemas/provision-tenant.ts` — Zod schema
- `lib/api/tenants.ts` — add `provisionTenant()` function (or extend existing). Sends `Idempotency-Key` header.
- `lib/hooks/use-provision-tenant.ts` — useMutation hook
- `mocks/handlers/tenants-store.ts` — in-memory state for tenants
- `mocks/handlers/audit-store.ts` — same pattern for audit logs

Modified:
- `app/(authenticated)/superadmin/tenants/page.tsx` — wire the "+ Provision tenant" CTA to open the modal (replace existing `comingInV1("Provision tenant")` toast)
- `mocks/handlers/tenants.ts` — GET handlers read from store, POST handler added
- `mocks/handlers/audit-logs.ts` — GET handlers read from store
- `mocks/fixtures/lookups.json` — verify all enum lists (tiers, industries, regions) present with correct codes and labels; add if missing
- `BUILD_PLAN.md` — Step 4.1 → DONE; Phase 4a entry; restructure Phase 4 and Phase 5 sections per the new structure
- `.env.example` — add `NEXT_PUBLIC_SIMULATE_ERRORS`

## Modal UX details

Modal composes the existing `<Modal />` primitive from Step 1.5.

**Width:** `lg` (640px-ish). The form has 9 fields plus help text and is taller than the medium default.

**Modal copy (verbatim from Lovable spec 7.2.4):**
- Title: `Provision new tenant`
- Subtitle: `Create a client organization with module access.`
- Cancel button: `Cancel`
- Submit button: `Provision tenant` (when idle), `Provisioning…` with spinner (when in flight)

**Field order on form (matches Lovable spec field listing):**
1. Tenant name (full width)
2. Display code (full width, with help text "Auto-generated from name if blank — short URL-friendly identifier, lowercase letters, numbers, hyphens, e.g., 'acme-retail'")
3. Industry (50% width) | Country (50% width) — same row
4. Tier (50% width) | Region (50% width) — same row
5. Primary contact (full width, label `Primary contact`, field `primary_contact_name`)
6. Contact email (full width)
7. Stores (50% width, integer input) | Monthly revenue (USD) (50% width, decimal input with $ prefix)

**Submit button states:**
- Disabled while form has validation errors (RHF `formState.isValid` false)
- Loading spinner + "Provisioning…" while mutation in flight
- Re-enabled on success or error

**Cancel behavior:** if form is dirty (any field changed from default), confirm dialog "Discard changes?" before closing. If form is pristine, close immediately. Same for Escape key and click-outside (per Lovable 7.2.9).

## Phase 4 / Phase 5 BUILD_PLAN restructure

Replace existing Phase 4 section with:

```
## Phase 4: Backend Integration

### Phase 4a: Anchor Write Flow
- Step 4.1 — Provision Tenant anchor flow (this step)

### Phase 4b: Read Wiring (incremental, runs against Sanjeev's deployed endpoints)
- URL prefix rename: /v1/ → /api/v1/ (mechanical find/replace, ~15min, prerequisite)
- Field rename: num_users → num_users_active (mechanical, prerequisite)
- Tenants reads — flip mocks/config.ts when Sanjeev confirms auth/URL/CORS
- Lookups reads — same flip
- Org nodes, Users, RBAC, Audit logs — when corresponding backend endpoints land
- Module Access, Guardrails — deferred until backend models the missing tables (tenant_module_access, guardrails+approvals)

### Phase 4c: Full Write Surface (deferred)
Deferred until backend write contracts ship. Estimated 30-40 mutations across 8 pages:
- Tenant: suspend, resume, edit, terminate
- User: invite, suspend, reactivate, reset MFA, impersonate, edit roles
- Org node: create, edit, deactivate, move
- Role: create custom, edit, delete, assign permissions
- Module access: enable/disable per tenant
- Guardrail: create, edit, pause/activate, delete
- Notification: mark as read, mark all as read
- Approval: approve, deny, request changes
```

Replace existing Phase 5 section with:

```
## Phase 5: Polish

### Phase 5a: Demo-Targeted Polish Tier 1
- Step 5.1 — pixel matching across 8 pages, drawer/modal animations, +N overflow on tenant cards, type-to-confirm on destructive dialogs (planned ~4 days)

### Phase 5b: Demo-Targeted Polish Tier 2 (deferred)
- Real impersonation banner countdown, sidebar collapse transition (planned ~1.5 days, deferred until Tier 1 ships and demo gap analysis confirms need)

### Phase 5c: Production Polish (deferred until post-demo)
- MSW activation race fix
- Base UI vs Radix compatibility audit (3 caught at v0; assume more)
- Per-form Zod validation rules (deeper than the Provision form's)
- WCAG 2.1 AA accessibility pass
- Light mode
- Localization (en-GB, en-US, en-IN)
- Real global search across tenants/users/roles
- Full optimistic-update-with-rollback for all mutations (anchor flow has it for one mutation)
```

## Process notes

- Pre-mark "no console errors" as ⚠️ in the structured pre-smoke check (activation race continues as Phase 5c).
- Pre-smoke self-check before browser smoke, same pattern as v0 steps. Check the schema, MSW handler shape, optimistic update flow, rollback path, and field-name parity (num_users vs num_users_active) before claiming readiness.
- Run `NEXT_PUBLIC_SIMULATE_ERRORS=true pnpm dev` for the rollback smoke (criterion 8). Otherwise leave it false.
- Smoke covers happy path, validation error path, conflict path, server error path, audit log composition, drawer-open-on-success.
- Cross-page smoke: after creating a tenant, navigate to /superadmin/audit — confirm the "Created tenant" entry is visible at the top. Persona switching while having created tenants in-memory should still show those tenants (they live in the store, not per-persona).
- Hard-reload smoke: after creating tenants in a session, hard-reload — confirm the new tenants are still visible (in-memory state survives within the session). Verify the dev-server restart resets state (expected behavior for v0).
- Production build smoke: run `pnpm build` after the implementation. v0 has only ever run `pnpm dev`. If `pnpm build` fails on TypeScript strict mode, env var requirements, or anything else dev mode tolerates — fix before claiming readiness.

## Smoke checklist

1. Open /superadmin/tenants. Click "+ Provision tenant" → modal opens with title "Provision new tenant".
2. Submit empty form → see required-field errors on name, tier, industry, country, primary_contact_name, contact_email. (Region defaults to US, tier defaults to SMB, stores defaults to 1 — these aren't invalid on submit.)
3. Type invalid email in contact_email → see field-level error on blur.
4. Type uppercase in display_code → on blur, value auto-lowercases (no error shown).
5. Type invalid display_code (e.g., "ab" — too short, or "Acme Foods" — has space) → see field-level error.
6. Leave display_code blank, type name "Acme Foods Inc." → submit succeeds, MSW auto-generates display_code "acme-foods-inc" (visible on the new card).
7. Type display_code that collides with existing fixture (e.g., "buc-ees" or "zabka-group") → submit → see inline error on display_code field "Display code is already in use".
8. Type valid form values, submit → see loading state on button → see success → modal closes → toast "Tenant <name> provisioned" → list refreshes with new tenant card → drawer auto-opens for the new tenant → URL contains `?tenant=<id>`.
9. Navigate to /superadmin/audit → see new "Created tenant" entry at top of list with correct actor (current persona) and resource showing the new tenant name.
10. Set NEXT_PUBLIC_SIMULATE_ERRORS=true, restart dev server. Submit valid form repeatedly until 500 fires → see toast "Could not provision tenant. Please try again." → optimistic placeholder removed from list → modal stays open with form values preserved.
11. Cancel button on dirty form → confirm dialog. Cancel button on pristine form → modal closes immediately.
12. Press Escape on dirty form → confirm dialog. Press Escape on pristine form → modal closes.
13. Hard-reload page after creating 2-3 tenants → confirm they all still appear in the list.
14. Restart dev server → confirm in-memory state resets (only original fixture tenants visible).
15. With monthly_revenue_usd populated on form, submit → confirm card shows the formatted value (e.g., "$0.5k" for "500.00"); navigate to detail drawer (if shown) — confirm `monthly_revenue_as_of_date` populated to today.
16. Console clean modulo activation race; MSW logs `POST /v1/tenants` with 201/400/409/500 as appropriate; `Idempotency-Key` header visible in request.

## Ask before building

If you have questions about specific implementation details before starting, surface them rather than guessing. Specific things worth flagging upfront:

- Field name parity: confirm whether v0 fixtures use `num_users` or `num_users_active` (one of them will be in `mocks/fixtures/tenants.json` and `types/api.ts`). Use whatever's there; don't introduce drift.
- Whether `mocks/fixtures/lookups.json` already has all the enum lists this form needs, or whether the fixture needs extending.
- Whether to extend existing `mocks/handlers/tenants.ts` or split into a separate `tenants-write.ts` (style preference; either is fine).
- Whether the existing v0 detail handler is in-memory-store-aware or reads the static fixture (if static, also wire it to read from the store so newly-created tenants open in the drawer correctly).
- React Hook Form + Zod integration patterns specific to this codebase (whether you've already established a pattern at v0).

Post the pre-smoke self-check structured table when ready, same shape as v0 steps. After smoke passes, propose the commit. Expected commit message:

> Step 4.1: Provision Tenant anchor flow with optimistic update and rollback
>
> First write surface in the build. Modal form, Zod validation, MSW POST handler with in-memory state, optimistic insert with rollback, audit log composition, drawer-open on success.
>
> Bundled: BUILD_PLAN restructured into Phase 4a/4b/4c and Phase 5a/5b/5c reflecting current direction.
