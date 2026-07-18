# Prompt — Step 2.2: Tenants page

> Paste this after Step 2.1 is committed.

---

## Pre-flight

```bash
pwd
git log --oneline -5
pnpm tsc --noEmit                # zero
pnpm dev
# verify: dashboard renders, "Manage all →" navigates here (but page is just a placeholder right now)
```

Read `BUILD_PLAN.md` Step 2.2 and `Ithina_Admin_Frontend.md` section 7.2 for tenant card anatomy and workflows. Refer to `tenants-api-contract-v0.md` Part 1 (in backend repo) for the data shape this page consumes.

---

## Step ID and intent

**Step 2.2** — The Tenants page. Card grid with 7 tenants from fixtures. Search, 5 filter tabs, drawer detail.

This is a CLAUDE_CODE step.

---

## Scope in

### 1. Page layout

Path: `app/superadmin/tenants/page.tsx` (replaces placeholder).

```
+----------------------------------------------------------------+
| PageHeader                                                     |
|   title: "Tenants"                                             |
|   subtitle: "{n} client organizations · {m} stores"            |
|   primaryAction: "+ Provision tenant"  → toasts "v1"            |
+----------------------------------------------------------------+
| Search input                                                   |
| Filter tabs: [All] [Enterprise] [Mid-Market] [SMB] [Single-Store] |
+----------------------------------------------------------------+
| Card grid: 3 columns                                           |
| [card][card][card]                                             |
| [card][card][card]                                             |
| [card]                                                         |
+----------------------------------------------------------------+
```

Subtitle counts come from `useTenantStats()`.

### 2. Search and filter

Search: shadcn `Input` with placeholder "Search tenants...". Debounce 300ms via a small hook (`use-debounced-value.ts` in `lib/hooks/`). Pass debounced value as `search` query param to `useTenants()`.

Filter tabs: shadcn `Tabs`. Tab values: `ALL`, `ENTERPRISE`, `MID_MARKET`, `SMB`, `SINGLE_STORE`. Default `ALL`. Pass as `tier` param when not ALL.

Both should update URL search params (`?search=...&tier=...`) so navigation is bookmarkable. Use `useSearchParams()` and `useRouter().replace()` to manage URL state.

### 3. Tenant card

Component: `components/tenants/TenantCard.tsx`.

```typescript
type TenantCardProps = {
  tenant: Tenant;
  onClick: () => void;       // opens drawer
};
```

Card anatomy per spec section 7.2.3:

```
+--------------------------------------------------+
| [Avatar BU]  Buc-ee's                            |
|              Convenience / Fuel · USA            |
| [Tier: ENTERPRISE]  [Status: ACTIVE]             |
|                                                  |
| +---------+ +---------+ +---------+              |
| | Stores  | | Users   | | MRR     |              |
| |   47    | |  312    | | $48.5k  |              |
| +---------+ +---------+ +---------+              |
|                                                  |
| [ROOS] [Goal Console] [Pricing OS] [Perish...]   |
| (full module list, no +N truncation in v0)       |
+--------------------------------------------------+
```

Avatar: 2-letter initial monogram with coloured background (consistent colour per tenant; hash the tenant name to a colour).

Money formatting: parse the string `"48500.00"` to a number, format as `$48.5k` for thousands, `$48.5M` for millions. Helper in `lib/utils/format-money.ts`.

`null` MRR (FreshMart on trial): show `—`.

Module pills: shadcn `Badge` variant. Render all enabled modules; do not truncate to +N in v0.

Cursor pointer on hover; click anywhere on card opens drawer.

Kebab menu: hidden in v0 per the v0 affordance policy.

### 4. Tenant detail drawer

Component: `components/tenants/TenantDetailDrawer.tsx`.

Triggered from card click. Slides from right via `Drawer` primitive.

Content per spec section 7.2.7:

```
+----------------------------------------+
| [Avatar BU]  Buc-ee's              [×] |
| Convenience / Fuel · USA               |
| Onboarded 2025-08-14                   |
+----------------------------------------+
| PRIMARY CONTACT                        |
|   Tomasz Nowak                         |
|   tomasz.nowak@bucees.com              |
+----------------------------------------+
| MODULES ENABLED (5)                    |
| [ROOS] [Goal Console] [Pricing OS]     |
| [Perishables] [Promotions] [Admin]     |
+----------------------------------------+
| LIVE COUNTS                            |
|   Stores: 47    Users: 312             |
+----------------------------------------+
|                                        |
+----------------------------------------+
| [Edit tenant]  [Suspend]               |
+----------------------------------------+
```

Action row at bottom:

- "Edit tenant" button → `comingInV1("Edit tenant")`
- "Suspend" button (red) when `status === ACTIVE` → `comingInV1("Suspend tenant")`
- "Resume" button (green) when `status === SUSPENDED` → `comingInV1("Resume tenant")`

Data from `useTenant(id)` (the detail endpoint, hydrated from fixtures). If your fixture handler doesn't have a per-id endpoint yet, add one to `mocks/handlers/tenants.ts` that returns the matching tenant or 404.

### 5. URL state for the drawer

Open drawer state: track via URL search param `?tenant=<id>`. Closing the drawer removes the param. This makes drawer state shareable and survives reload.

### 6. Empty state

If `useTenants()` returns zero items (e.g., search filters out everything), render the `EmptyState` primitive:

- Title: "No tenants match your filter"
- Body: "Try a different search or filter."

(Spec calls this out as a defined empty state.)

### 7. Loading state

While `useTenants()` is loading, render a 3×3 grid of card skeletons.

### 8. Error state

If hook errors, render `ErrorInline` with retry CTA. Retry calls `refetch()` on the query.

---

## Scope out

- Provision modal (the "+" button toasts "v1"; modal is not built)
- Edit modal
- Suspend/resume confirmation dialogs (toast "v1" instead)
- Kebab menu actions
- `+N` module pill overflow (render all; truncation is polish)
- Type-to-confirm for destructive actions (deferred)
- Animations on drawer slide

---

## Acceptance criteria

1. `/superadmin/tenants` renders the 7 fixture tenants as cards in a 3-column grid
2. Subtitle shows correct counts from stats endpoint
3. Search input filters live (debounced 300ms); URL updates with `?search=...`
4. Filter tabs filter by tier; URL updates with `?tier=...`
5. "+ Provision tenant" button toasts "Coming in v1"
6. Clicking a card opens the right-side drawer with tenant details; URL updates with `?tenant=<id>`
7. Closing the drawer (× button or click outside) removes the URL param
8. Drawer "Edit tenant" / "Suspend" / "Resume" buttons toast "v1"
9. Reloading the page with `?tenant=<id>` in URL re-opens the drawer for that tenant
10. Empty state renders when filters yield zero results
11. Loading skeletons render before fixtures load
12. Status chip and tier chip render with correct colours
13. `pnpm tsc --noEmit` exits zero
14. No console errors
15. `BUILD_PLAN.md` Step 2.2 flipped to DONE

---

## After completing the step

1. Confirm acceptance
2. Report files added; any fixture/handler updates
3. Flag any deviation from prototype layout (card sizing, spacing, etc.)
4. Update BUILD_PLAN.md
5. Propose commit:
   ```
   git add -A
   git commit -m "Step 2.2: Tenants page with card grid, filters, detail drawer"
   ```
6. Wait before Step 2.3

---

## If you hit a snag

- Currency formatting edge cases (FreshMart's null MRR): handle the null branch explicitly, render `—`.
- Avatar colour hashing: a simple `nameHash % palette.length` is fine. Consistency per tenant matters; the exact colour does not.
- Drawer + URL state interaction (drawer opens but URL doesn't update on programmatic open): use a single source of truth — either the URL drives the drawer (open when `?tenant=<id>` present) or local state drives it. Prefer URL-driven for shareability.
- Detail handler returns a fuller shape than the list (LIVE_COUNTS, lifecycle, primary_contact): make sure your fixture has this richer shape for at least Buc-ee's; other tenants can use a minimal shape.
