# Step 5.2.2 — Permission Matrix Redesign

## Context and intent

5.2.1 closed Org Tree redesign. The permission matrix is the second and last Tier 2 page that needs structural rework. After this, Phase 5b (Tier 2 polish) closes; the build is at "demo-perfect" state pending Phase 4b/4c (backend wiring + write surface).

User's diagnosis: "no grouping — all 40 actions in one flat list, hard to find a specific permission."

Per the DDL (`Ithina_postgres_SQL_DDL_rbac_v2.sql`), the permission catalog is a list of valid `(module, resource, action, scope)` 4-tuples:

- **Resources (12):** PRICING_RULES, MARKDOWNS, EXPIRING_ITEMS, WASTE_LOG, DONATION_ROUTING, CAMPAIGNS, USERS, ROLES, AUDIT_LOG, TENANTS, STORES, ORG_NODES
- **Actions (6):** VIEW, CONFIGURE, EXECUTE, APPROVE, OVERRIDE, AUDIT
- **Scopes (4):** GLOBAL, TENANT, REGION, STORE

The matrix renders these tuples as rows × roles as columns. v0 ships them flat — ~40 rows in one scroll, no grouping, no hierarchy. The redesign groups rows by resource (per user's Q1 answer), with the first group expanded by default (per Q2).

## Out of scope

- Changing the underlying permission catalog or role definitions (data layer)
- Adding write capability (toggle a cell to grant/revoke) — Phase 4c territory
- Search/filter UI within matrix (defer to 5.2.x if needed)
- Touching the Role catalog tab on `/superadmin/roles` (already grouped in 5.1.4)

## Aesthetic anchor

Reference points: **Linear's keyboard shortcuts settings**, **Notion's database properties**, **GitHub's repository permissions matrix**. Compact rows (~32px), sticky headers (top row + first column), grouped sections with collapsible headers, small clear granted/denied indicators. Not Excel — no gridlines crowding every cell.

## Acceptance criteria

1. **Rows grouped by resource.** 12 resource group sections. Each header shows: resource name (formatted, e.g., "Tenants" not "TENANTS"), permission count `(N)`, expand/collapse caret. Headers use `text-label` token (uppercase + tracking).
2. **Default expansion: first group expanded.** TENANTS group expanded on first load (alphabetical or DDL order — see below). Other 11 groups collapsed.
3. **Resource ordering: by module.** Resources from the same module are adjacent. Order:
   - Pricing OS: PRICING_RULES, MARKDOWNS
   - Perishables Assistant: EXPIRING_ITEMS, WASTE_LOG, DONATION_ROUTING
   - Promotions Assistant: CAMPAIGNS
   - Admin: USERS, ROLES, AUDIT_LOG, TENANTS, STORES, ORG_NODES
   This matches the DDL comment order. Module name shows as a divider above the first resource of that module.
4. **Row content: action + scope.** Each row shows the action and scope concatenated, e.g., `VIEW · TENANT`, `CONFIGURE · GLOBAL`. Action is `text-body`; scope dot-separator `text-foreground-muted`; scope name `text-secondary text-foreground-muted`.
5. **Audience tabs.** The matrix has tabs above it: "Platform roles" (4 roles) and "Tenant roles" (11 roles). User picks one; matrix shows that audience's roles as columns. Default tab: Tenant roles (more common usage).
6. **Sticky headers.** Top row (role names) sticky on vertical scroll. First column (permission name) sticky on horizontal scroll. Both sticky simultaneously when both axes scroll.
7. **Cell granted/denied indicator.** Granted cell shows a small filled circle in `--success` (`bg-emerald-600 dark:bg-emerald-400`, ~6px diameter). Denied cell shows nothing (empty cell). No checkmarks, no Xs, no shaded backgrounds.
8. **Resource group header counts.** Group header shows `(N)` count of permissions within that resource. Counts are computed from the catalog, not hardcoded.
9. **Group expand/collapse animation.** Same fade pattern as Org Tree: 150ms duration, ease-out enter, ease-in exit. `prefers-reduced-motion` respected.
10. **Module section dividers.** Above the first resource of each module, render a small label divider: `text-label text-foreground-subtle` reading the module name, with a thin `border-t border-border` line. Subtle.
11. **Empty matrix state.** If the catalog is empty (shouldn't happen but defensive), show "No permissions defined."
12. **Existing `/superadmin/roles` tab navigation preserved.** This page has at least two tabs: Role catalog (already grouped in 5.1.4) and Permission matrix (this step). Tab switching unchanged.
13. The 8 pages still render with the same content and behavior. Permission Matrix is the only page redesigned this step.
14. `pnpm tsc --noEmit` exits zero.
15. `pnpm lint` exits zero.
16. `pnpm build` succeeds.
17. No console errors (modulo activation race; pre-mark ⚠️).
18. `prefers-reduced-motion` respected for group expand/collapse.
19. Both themes render correctly (no 5.1.2 regression).
20. BUILD_PLAN.md updated: Step 5.2.2 → DONE; Phase 5b marked complete.
21. PATTERNS.md updated with "Permission Matrix component" section: data shape (4-tuples), grouping strategy, sticky header pattern, default expansion.

## Data shape

The matrix consumes:

```ts
type Permission = {
  id: string                  // canonical permission code
  module: ModuleEnum
  resource: ResourceEnum
  action: ActionEnum
  scope: ScopeEnum
}

type Role = {
  id: string
  name: string
  audience: 'PLATFORM' | 'TENANT'
  permission_ids: string[]    // which permissions this role grants
}

type MatrixData = {
  permissions: Permission[]
  roles: Role[]
}
```

Where the data lives:
- `mocks/fixtures/permissions.json` — likely already exists from v0; check
- `mocks/fixtures/roles.json` — exists, with each role's `permission_ids` array

The matrix renders by:
1. Group permissions by `resource`
2. For each resource group: render header + rows
3. Each row: render `action · scope` label + N cells (one per role in current audience tab)
4. Each cell: filled circle if `role.permission_ids.includes(permission.id)`, else empty

## Component structure

### `components/roles/PermissionMatrix.tsx`

Top-level. Owns the audience tab state, scroll containers, resource group expansion state.

```ts
{
  permissions: Permission[]
  roles: Role[]
  initialAudience?: 'PLATFORM' | 'TENANT'  // default 'TENANT'
}
```

Internally:
- Tabs at top using base-ui Tabs (TabsIndicator from 5.1.3 already wired)
- Below tabs: scroll container with two-axis sticky positioning (CSS grid + position: sticky)
- Computes resource groups: groups permissions by resource, preserves DDL order, attaches module label per group
- Manages expansion state: `Set<ResourceEnum>` of expanded resources, default `{TENANTS}` (or first in module order)

### `components/roles/PermissionMatrixGroup.tsx`

A single resource group section. Header + rows.

```ts
{
  resource: ResourceEnum
  module: ModuleEnum               // for the divider above
  showModuleDivider: boolean       // true if first resource of its module
  permissions: Permission[]        // permissions in this resource
  roles: Role[]                    // current audience's roles
  isExpanded: boolean
  onToggle: () => void
}
```

### `components/roles/PermissionMatrixRow.tsx`

Single permission row. Permission label cell (sticky left) + role cells.

```ts
{
  permission: Permission
  roles: Role[]
}
```

Renders: action+scope label in left sticky column + N role cells with filled-circle if granted.

### Sticky-headers technique

CSS grid with a fixed first column + scrollable rest. Top row is `position: sticky; top: 0`. First column is `position: sticky; left: 0`. The intersection cell (top-left, where role-header column meets permission-row column) stays both top-stuck and left-stuck — this is the trickiest cell. It needs `z-index` higher than other sticky elements so it stays on top during diagonal scroll.

```css
.matrix-corner    { position: sticky; top: 0; left: 0; z-index: 30; }
.matrix-header    { position: sticky; top: 0; z-index: 20; }
.matrix-rowlabel  { position: sticky; left: 0; z-index: 20; }
.matrix-cell      { /* no sticky */ }
```

Test the sticky behavior with both axes scrolled. The corner cell is the most common implementation bug — it should always show "Permission" or empty, never duplicate content.

## Visual specifics

### Group header

```
▼  TENANTS (8)        Admin
   VIEW · GLOBAL       ●  ○  ○  ...
   VIEW · TENANT       ○  ●  ●  ...
   CONFIGURE · GLOBAL  ●  ○  ○  ...
   ...
```

- Caret on the left
- Resource name (formatted) in `text-body-strong`
- Permission count in `text-secondary text-foreground-muted` after the resource name
- Module name in `text-label text-foreground-subtle` aligned to the right of the row, before the matrix cells start
- Header has subtle `bg-surface-raised` on hover; no background by default
- Click anywhere on header toggles expansion

### Module divider

Above the first resource of each module (e.g., the row above PRICING_RULES which starts the Pricing OS module):

```
─── Pricing OS ───────────────────
▼  PRICING_RULES (4)   Pricing OS
   ...
```

A thin `border-t border-border` line, with the module name in `text-label text-foreground-subtle` left-aligned. ~8px vertical padding above the first group below it.

For the very first module, no divider needed (the page header already serves that role).

### Permission row

- Left column (sticky): action + scope (`VIEW · TENANT`)
  - Action in `text-body`
  - Dot separator (` · `) in `text-foreground-muted`
  - Scope in `text-secondary text-foreground-muted`
- Cells: 32px tall, ~80px wide
- Granted cell: small `bg-emerald-600` (light) / `bg-emerald-400` (dark) circle, 6px diameter, centered
- Denied cell: empty
- Row hover: subtle `bg-surface-raised` background applies to the whole row (sticky cell + scroll cells)
- No row-level borders. Use spacing only.

### Cell sizing and density

- Row height: 32px
- Column width: 80px
- Header row height: 40px (slightly taller for readability)
- Sticky permission column width: 240px (room for `CONFIGURE · GLOBAL` plus padding)

These are starting values; adjust on smoke if any feel cramped or excessive.

### Cell hover behavior

On hover over a cell, show a small tooltip with the full permission code: e.g., "ADMIN.TENANTS.VIEW.GLOBAL". Helpful for understanding what the cell represents without interpreting the row + column intersection. Use existing shadcn Tooltip primitive.

## Audience tabs

Above the matrix: tab list with "Tenant roles" (default) and "Platform roles" tabs. Switching tabs swaps which roles render as columns. The matrix re-keys (component remount via React `key` prop) on tab change so scroll position resets.

Don't try to filter columns inline — re-render is cleaner and avoids weird layout bugs.

Tab counts in the label: "Tenant roles (11)" / "Platform roles (4)". Computed from the roles fixture.

## Files modified

Likely:
- `components/roles/PermissionMatrix.tsx` — top-level, rewrite
- `components/roles/PermissionMatrixGroup.tsx` — new (or rewrite if existing)
- `components/roles/PermissionMatrixRow.tsx` — new
- `app/(authenticated)/superadmin/roles/page.tsx` — verify tabs / pass props through
- `mocks/fixtures/permissions.json` — verify shape; extend if missing tuples (see Ask)
- `BUILD_PLAN.md`, `PATTERNS.md`

Files to leave alone:
- `mocks/fixtures/roles.json` — already exists, assume shape correct
- The Role catalog tab (already grouped in 5.1.4)
- Permission matrix's role-detail drawer if any (out of scope unless audit shows it's broken)

Estimated diff: 5-10 files. Concentrated in 3 components + fixture verification.

## Smoke checklist

After implementing:

1. **Open `/superadmin/roles`**, navigate to Permission Matrix tab.
2. **Tabs visible:** "Tenant roles (11)" / "Platform roles (4)". Tenant roles is default-active.
3. **Module divider above first resource of each module.** "Pricing OS" appears above PRICING_RULES; "Perishables Assistant" appears above EXPIRING_ITEMS; etc.
4. **TENANTS group expanded on first load.** All other groups collapsed (caret right-pointing).
5. **TENANTS group rows visible.** Format: `VIEW · TENANT`, `CONFIGURE · GLOBAL`, etc. Cells per role show filled green circle when granted, empty otherwise.
6. **Click ROLES group header → expands.** Subtle fade animation. Caret rotates to down. Click again → collapses.
7. **Hover a granted cell → tooltip** shows full permission code (e.g., `ADMIN.TENANTS.VIEW.GLOBAL`).
8. **Scroll vertically.** Header row stays stuck at top. Roles list visible always.
9. **Scroll horizontally.** First column (permission name) stays stuck at left. Permission name visible always.
10. **Both axes scrolled.** Top-left corner cell stays in place; doesn't duplicate or break.
11. **Switch to Platform roles tab.** Matrix re-keys, shows 4 platform roles as columns. Same group expansion behavior.
12. **Click row to no effect** (rows are not interactive in this step; cell hover tooltip is the only interaction). Row hover bg shows.
13. **Reduced motion check.** Enable in dev tools → expand/collapse instant. Functional.
14. **Both themes render.** Toggle Light → Dark. Granted-circle color contrasts both backgrounds.
15. **Other 7 pages unaffected.** Walk Dashboard → Tenants → Users → Org → Modules → Guardrails → Audit. No regression.
16. Console clean modulo activation race.
17. `pnpm build` succeeds.

## Process notes

- Pre-mark "no console errors" as ⚠️ (activation race).
- Pre-smoke self-check before browser smoke. Verify the sticky-corner cell behaves correctly with both axes scrolled (most common implementation bug).
- The 80px column width × 11 columns = 880px wide. Plus 240px sticky column = 1120px total matrix width. Most desktops handle this without horizontal scroll. If the user is on a narrower viewport (laptop), horizontal scroll engages. That's correct behavior.
- The Tooltip on cell hover is non-trivial — applying `<Tooltip>` to ~440 cells (40 rows × 11 columns) might be a render perf concern. Use a single tooltip pattern at the matrix-container level with delegated event handling, or accept the per-cell tooltip cost (likely fine for ~500 cells).
- If `permissions.json` doesn't exist or is sparse, the smoke can't fully exercise the redesign. Surface the fixture state up front before building.
- Don't add column sort/filter UI. The matrix is a reference view; sorting permissions doesn't help the primary "is this role's permission set right" task.
- The granted-circle uses success green specifically because permission *grants* are the positive state. Don't use blue (primary) — primary is for CTA, not status.

## Ask before building

Things worth surfacing upfront:

- **Fixture state.** Does `mocks/fixtures/permissions.json` exist? How many tuples? Are all 12 resources represented? Are all 6 actions represented? If sparse (e.g., only 10 tuples vs the 40-ish v0 ships), the redesign demos against thin data. Surface coverage before building.
- **Existing matrix component name.** What does v0 call it? `PermissionMatrix.tsx`, `PermissionsView.tsx`, or something else? Naming the rewrite target accurately.
- **Module super-grouping (the divider above resources of the same module) — overhead worth it?** Adds visual organization at the cost of vertical space. My lean: yes, ship it. The four module groupings (Pricing OS / Perishables / Promotions / Admin) are meaningful, not arbitrary. But if the audit shows v0 doesn't have module data on permissions and we'd be inferring from resource_enum order alone, surface for go/no-go.
- **Cell tooltip implementation.** Per-cell `<Tooltip>` (clear, ~440 instances) vs. delegated single tooltip on the matrix container (slightly more code, no perf concern). My lean: per-cell — render perf likely fine, code is clearer.
- **Default group expansion: TENANTS or first-by-module-order (PRICING_RULES)?** The prompt says "TENANTS" but module order would put Admin's resources last. If the right module ordering puts Admin (with TENANTS, USERS, etc.) at the bottom, defaulting to TENANTS means scrolling past 6+ collapsed groups to see the expanded one. Three options:
  - (a) Default expand TENANTS regardless of position. User scrolls to find it.
  - (b) Default expand PRICING_RULES (first in module order).
  - (c) Reorder so Admin module comes first (matching most-used) and default expand TENANTS at top.
  My lean: (c). Admin is the most relevant module for governance; reordering puts the most-used groups at top.

Post the pre-smoke self-check structured table when ready, same shape as v0 + 4.1 + 5.1.x + 5.2.1 steps. After smoke passes, propose the commit. Expected commit message:

> Step 5.2.2: Permission Matrix redesign
>
> Group rows by resource (12 groups). Module dividers above first resource of each module. First group expanded on default; rest collapsed. Audience tabs (Tenant / Platform) above the matrix.
>
> Sticky headers (top row + first column). Granted-cell shows small green circle; denied cell empty. Cell hover shows full permission code in tooltip.
>
> Tier 2 closes. Phase 5b complete. Build at demo-perfect state pending Phase 4b/4c (backend wiring + write surface).
