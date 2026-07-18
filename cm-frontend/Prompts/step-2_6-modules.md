# Prompt — Step 2.6: Module Access

> Paste this after Step 2.5 is committed.

---

## Pre-flight

```bash
pwd
git log --oneline -5
pnpm tsc --noEmit                # zero
pnpm dev
```

Read `BUILD_PLAN.md` Step 2.6, `Ithina_Admin_Frontend.md` section 7.6 (Module Access), and `tenants-api-contract-v0.md` Part 5 in backend repo.

**Important context.** The backend doesn't yet have a `tenant_module_access` table. This page is mock-only in v0; wiring waits for that table to ship. Don't try to design around the gap; just build against the contract shape `tenants-api-contract-v0.md` describes.

---

## Step ID and intent

**Step 2.6** — The Module Access page. 6 module summary cards top, tenant × module toggle matrix below.

This is a CLAUDE_CODE step.

---

## Scope in

### 1. Page layout

Path: `app/superadmin/modules/page.tsx`.

```
+----------------------------------------------------------------+
| PageHeader                                                     |
|   title: "Module Access"                                       |
|   subtitle: "Enable or disable Ithina modules per tenant.      |
|              Disabling instantly revokes role permissions."    |
|   (no primary action)                                          |
+----------------------------------------------------------------+
| 6 module summary cards in 3×2 grid                             |
+----------------------------------------------------------------+
| Tenant × Module matrix                                         |
| | Tenant         | ROOS | Goal | Pricing | Perish | Promo | Admin | |
| | Buc-ee's       |  ✓   |  ✓   |    ✓    |   ✓    |   ✓   |   🔒   | |
| | Żabka          |  ✓   |  ✗   |    ✓    |   ✓    |   ✓   |   🔒   | |
| | ...                                                          |
+----------------------------------------------------------------+
```

### 2. Module summary cards (6)

Component: `components/modules/ModuleSummaryCard.tsx`.

For each of: ROOS, GOAL_CONSOLE, PRICING_OS, PERISHABLES_ASSISTANT, PROMOTIONS_ASSISTANT, ADMIN.

Each card:
- Icon (lucide; pick reasonable matches: `Cpu` ROOS, `Target` Goal, `DollarSign` Pricing, `Apple` Perishables, `Megaphone` Promotions, `Settings` Admin)
- Module name
- Tagline (from fixture/lookup)
- "Enabled in N / M tenants" line
- Click: opens a future module detail panel (toast "v1" or no-op for v0)

Data: `useModuleSummary()` returns 6 entries from `mocks/fixtures/modules.json`.

### 3. Tenant × Module matrix

Component: `components/modules/ModuleAccessMatrix.tsx`.

Use shadcn `Table`. First column: tenant (avatar + name + tier chip). Next 6 columns: each module as a header.

Each cell: a toggle. Use shadcn `Switch` primitive.

Cell state from fixture data: each tenant has `modules: [{module, enabled, enabled_at}]` matching the contract shape.

Click toggle: toasts "v1". The toggle state visually flips for a moment (optimistic UI), then reverts on the next render (since no actual write happens). Acceptable v0 behaviour; document this in a code comment.

The Admin column toggles render as locked-on with a 🔒 icon and tooltip "Admin module is required for every tenant and cannot be disabled." Click: no-op, no toast.

### 4. Filter (optional but useful)

Status filter dropdown above the matrix:
- "All tenants"
- "Active only"
- "Trial only"
- "Suspended"

Default: hides SUSPENDED and TERMINATED (per contract section 35.1 default).

### 5. Empty states

The page is never empty (always has 7 tenants, 6 modules). Skip empty state.

### 6. Loading

Cards: 6 skeletons.
Matrix: 7 row skeletons.

---

## Scope out

- Module detail panel (the click-card behaviour)
- Disable confirmation dialog with reason input (toast "v1" instead of opening dialog)
- Real cascade preview ("disabling will revoke X permissions for Y users")
- Bulk operations
- Module enablement event timeline

---

## Acceptance criteria

1. `/superadmin/modules` renders with 6 summary cards in 3×2 grid
2. Cards show icon, name, tagline, "Enabled in N/M tenants" with correct counts from fixtures
3. Card click toasts "v1"
4. Matrix renders with 7 tenants as rows, 6 modules as columns
5. Cell toggles show current state from fixtures
6. Click any non-Admin toggle: optimistic flip, then toasts "v1", then reverts on re-render
7. Admin column locked-on with lock icon and tooltip
8. Status filter dropdown narrows tenants
9. `pnpm tsc --noEmit` exits zero
10. No console errors
11. BUILD_PLAN.md Step 2.6 flipped to DONE

---

## After completing the step

1. Confirm
2. Report fixture data choices (which modules each tenant has enabled per Appendix E)
3. Update BUILD_PLAN.md
4. Propose commit:
   ```
   git add -A
   git commit -m "Step 2.6: Module Access page with summary cards and toggle matrix"
   ```
5. Wait before Step 2.7

---

## If you hit a snag

- Toggle optimistic-then-revert: this is a v0 compromise. Real wiring will use TanStack Query `useMutation` with onMutate/onError for actual optimistic UI. For v0, just toast and let the toggle visually settle back.
- Module enablement counts per Appendix E: Buc-ee's all 5 non-Admin modules. Żabka 4 (no Goal Console). SmartStore 2 (Pricing OS, Perishables). FreshMart 1 (Perishables). CornerStop 2 (Perishables, Promotions). GreenLeaf 2 (ROOS, Perishables). Infomil 4 (no Promotions). Plus Admin enabled for all 7. Verify counts match.
- shadcn `Switch` styling for locked state: pass `disabled` prop, override colour with Tailwind classes, render the lock icon overlaid or beside.
