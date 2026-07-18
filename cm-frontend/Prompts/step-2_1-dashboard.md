# Prompt — Step 2.1: Platform Dashboard

> Paste this after Step 1.5 is committed. Phase 2 (page builds) begins here.

---

## Pre-flight

```bash
pwd
git log --oneline -5             # Step 1.5 commit at top
pnpm tsc --noEmit                # zero
pnpm dev
# verify: chrome works, persona switcher works, demo page renders all primitives
```

Read `BUILD_PLAN.md` Step 2.1 and `Ithina_Admin_Frontend.md` section 7.1 (Platform Dashboard) for the layout and KPI specs.

---

## Step ID and intent

**Step 2.1** — The Platform Dashboard page. The default landing after login.

8 KPI cards in a 4×2 grid, plus two panels below: Top tenants by users and Recent activity. All data from MSW mocks via the `useDashboard*` hooks created in Step 1.3.

This is a CLAUDE_CODE step.

---

## Scope in

### 1. Page layout

Path: `app/superadmin/dashboard/page.tsx` (replaces the placeholder from Step 1.3).

```
+----------------------------------------------------------------+
| PageHeader                                                     |
|   title: "Superadmin Dashboard"                                |
|   subtitle: "Govern every tenant, module, role and approval    |
|              rail across Ithina."                              |
|   right side: green dot + "All systems operational"            |
+----------------------------------------------------------------+
| KPI grid: 4 columns × 2 rows                                   |
| [card 1][card 2][card 3][card 4]                               |
| [card 5][card 6][card 7][card 8]                               |
+----------------------------------------------------------------+
| Two-column panel layout                                        |
| +-------------------------+ +-------------------------+        |
| | Top tenants by users    | | Recent activity         |        |
| | (5 rows)                | | (10 rows)               |        |
| +-------------------------+ +-------------------------+        |
+----------------------------------------------------------------+
```

Use Tailwind grid for the KPI section (`grid grid-cols-4 gap-4` on desktop; collapse to 2 on tablet, 1 on mobile is fine but mobile is out of v0 scope per spec section 16).

### 2. KPI cards

Component: `components/dashboard/KpiCard.tsx`

```typescript
type KpiCardProps = {
  icon: ReactNode;
  iconColour: "blue" | "purple" | "teal" | "green" | "orange" | "red";
  metric: string;            // primary number, large
  label: string;             // "Active tenants"
  subtext?: string;          // "2 trial · 1 suspended"
  delta?: string;            // "↗ +1 this wk"
  onClick?: () => void;      // navigates on click
};
```

Card visual: icon top-left in a coloured-tint rounded square, primary metric large, label below, subtext muted, delta in green/red small text in corner.

The 8 cards (data from `useDashboardKPIs()`):

| # | Icon (lucide) | Tint | Metric | Label | Subtext | Delta | On click |
|---|---|---|---|---|---|---|---|
| 1 | Building2 | blue | "5 / 7" | "Active tenants" | "2 trial · 1 suspended" | "↗ +1 this wk" | `/superadmin/tenants?status=ACTIVE` |
| 2 | Users | purple | "8,438" | "Platform users" | "across all tenants" | "↗ +184 / 30d" | `/superadmin/users` |
| 3 | Store | teal | "10,084" | "Stores under mgmt" | "9 countries" | — | `/superadmin/org` |
| 4 | DollarSign | green | "$308.1k" | "MRR" | "recurring" | "↗ +12.4%" | `/superadmin/tenants?sort=-monthly_revenue_usd` |
| 5 | Shield | orange | "7" | "Pending approvals" | "across guardrails" | — | `/superadmin/guardrails` |
| 6 | Activity | red | "23" | "Guardrails fired (24h)" | "3 escalations" | — | `/superadmin/guardrails` |
| 7 | Lock | purple | "1" | "Custom roles" | "of 15 total" | — | `/superadmin/roles` |
| 8 | Boxes | teal | "6" | "Modules deployed" | "enabled per tenant" | — | `/superadmin/modules` |

Use `useRouter().push()` from `next/navigation` for clicks.

### 3. Top tenants panel

Component: `components/dashboard/TopTenantsPanel.tsx`

Data from `useTopTenants()` (returns 5 tenants sorted by user count descending).

Header: "Top tenants by users" + "Manage all →" link to `/superadmin/tenants`.

Each row:
- Avatar (initials, coloured background)
- Tenant name + "industry · country" subtitle
- Right-aligned: user count + store count
- Tier chip

Click row: opens tenant detail drawer. The drawer is built fully in Step 2.2; for now, just emit a toast or `console.log("would open drawer", tenant.id)` so the dashboard works. Tag this with a `// TODO: wire to drawer in Step 2.2` comment.

### 4. Recent activity panel

Component: `components/dashboard/RecentActivityPanel.tsx`

Data from `useRecentActivity()` (returns 10 most recent audit events).

Header: "Recent activity" + "Audit log →" link to `/superadmin/audit`.

Each row:
- Coloured status dot (green for SUCCESS, amber for PENDING, red for DENIED)
- Actor name in bold
- Action label (in muted prose: "Anjali Mehta enabled module Promotions Assistant for Buc-ee's")
- Timestamp on the right (relative format via `date-fns formatDistanceToNow`, e.g. "2 min ago")

Click row: navigates to `/superadmin/audit/${eventId}` for now (the audit detail drawer is built in Step 2.8; navigation just lands on the audit page for v0).

### 5. "All systems operational" indicator

Top-right of the page header. Green dot + text. Static in v0.

### 6. Loading state

While `useDashboardKPIs()` etc. are loading, render skeleton placeholders matching the 4×2 grid + two panels. Use the `Skeleton` primitive from Step 1.5.

### 7. Error state

If any of the dashboard hooks errors, render an error state in that section only (not the whole page). Pattern:

```tsx
{error ? <ErrorInline message="Could not load tenants" /> : <TopTenantsPanel data={data} />}
```

Create a small `components/shared/ErrorInline.tsx` if it doesn't exist yet. Keeps the rest of the page useful even if one section fails.

### 8. Data hooks (verify)

`useDashboard*` hooks were stubbed in Step 1.3. Confirm they return what this page needs:

- `useDashboardKPIs()` → `{ active_tenants, platform_users, stores_under_mgmt, mrr_usd, pending_approvals, guardrails_fired_24h, custom_roles, modules_deployed }` plus deltas where applicable
- `useTopTenants()` → array of 5 `Tenant` (subset shape)
- `useRecentActivity()` → array of 10 `AuditEvent` (subset shape)

If any of these don't exist or shape doesn't match, update `lib/api/dashboard.ts` and `mocks/handlers/dashboard.ts` and `mocks/fixtures/dashboard.json` to provide the data the page needs. Note any changes in your final report.

---

## Scope out

- Tenant detail drawer (Step 2.2)
- Audit event detail drawer (Step 2.8)
- Real-time updates (no polling, no SSE in v0)
- Pixel-exact spacing matching the prototype screenshots (deferred polish)
- Light mode

---

## Acceptance criteria

1. `/superadmin/dashboard` renders the 8 KPI cards in a 4×2 grid
2. Each card click navigates to the right destination (verify all 8)
3. Top tenants panel shows 5 tenants from fixtures with avatar, name, counts, tier
4. Recent activity panel shows 10 audit events with status dot, actor, action, timestamp
5. "Manage all →" navigates to `/superadmin/tenants`
6. "Audit log →" navigates to `/superadmin/audit`
7. Page header shows title, subtitle, "All systems operational" indicator
8. Loading skeletons render before fixtures load
9. `pnpm tsc --noEmit` exits zero
10. No console errors
11. `BUILD_PLAN.md` Step 2.1 flipped to DONE

---

## After completing the step

1. Confirm acceptance
2. Report files added; any fixture updates needed
3. Flag any KPI numbers that are placeholders (e.g., the "8,438 platform users" doesn't reconcile with 17 fixture users — note this; the dashboard shows the demoed numbers from Appendix E, not the fixture row counts)
4. Update BUILD_PLAN.md
5. Propose commit:
   ```
   git add -A
   git commit -m "Step 2.1: Platform Dashboard with KPIs, top tenants, recent activity"
   ```
6. Wait before Step 2.2

---

## If you hit a snag

- Fixture data mismatch: the dashboard headline numbers ("8,438 users") are the prototype's demo numbers, not derived from row counts. Treat them as static fixture values for now. The discrepancy resolves when wiring lands and real backend computes them.
- Avatar initials calculation: implement a small helper `lib/utils/initials.ts` that takes a name and returns up to 2 uppercase initials.
- Coloured tint backgrounds for icons: use Tailwind opacity utilities (`bg-blue-500/10` etc.). Don't try to be exact-pixel; "close enough" is the v0 bar.
