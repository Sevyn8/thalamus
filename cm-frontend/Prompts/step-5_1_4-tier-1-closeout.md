# Step 5.1.4 — Tier 1 Polish Closeout

## Context and intent

5.1.1 (tokens), 5.1.2 (light theme + toggle), 5.1.3 (animations) shipped. The build feels deliberate and alive. Three Tier 1 items remain that close out the polish foundation:

1. **+N module overflow** — Buc-ee's tenant card has 6 modules wrapping awkwardly across two rows. Per Lovable spec and the original v0 prompt, cards should show 4 module pills + "+N more" overflow, with full list visible in the drawer.
2. **Type-to-confirm dialog pattern** — Phase 4c will need destructive confirmations (suspend tenant, terminate tenant, delete role, etc.). Get the dialog UX right now so 4c writes have a reference pattern, not so they can be made functional now (those still toast "v1").
3. **Sidebar discoverability** — collapse/expand affordance is built but undersold. Tooltip + keyboard shortcut.
4. **Roles catalog grouping** — `/superadmin/roles` catalog renders 15 roles in a flat list. Group into "Platform roles" (4 roles) and "Tenant roles" (11 roles) sections. Structural but mechanical fix.
5. **Card density audit** — generic pixel pass across the 8 pages catching anything ad-hoc that escaped 5.1.1's sweep. Final cleanup, not a major surface.

After this step, Tier 1 is done. Tier 2 (Org Tree redesign in 5.2.1, permission matrix redesign in 5.2.2) addresses the page-specific UX work that's outside polish scope.

## Out of scope for this step

- **Org Tree redesign** — Tier 2 work, deferred to 5.2.1
- **Permission matrix redesign** — Tier 2 work, deferred to 5.2.2 (with note: matrix needs grouping; 40 actions in flat list)
- **Audit log actor cell fix** — user retracted this complaint after re-walking
- **Sidebar collapse animation** — already plain CSS transition; if it feels janky, address in 5.2.x

## Sub-step 1: +N module overflow on tenant cards

### What it solves

`TenantCard` currently renders all enabled modules as pills in a wrapping row. Buc-ee's has 6 modules; the second row is visually crowded and the card looks unbalanced compared to single-row tenants.

### Implementation

In `components/tenants/TenantCard.tsx`, change module pill rendering:

- If `modules.length <= 4`: render all pills as today
- If `modules.length > 4`: render first 4 pills + a `+N` chip showing the overflow count (e.g., `+2`)
- The `+N` chip uses the same chip recipe as a Module pill (zinc/grey tone, ring), but with `+{n}` text and a slightly muted appearance
- Hover/click on `+N` chip is non-interactive in 5.1.4 (can be a tooltip future-state). Drawer already shows full module list.

Sort order matters: keep the existing module sort (whatever v0 ships — likely `module_order` from the lookups fixture). Don't re-sort just to fit a "best 4" subset.

### Specific cards affected

- Buc-ee's: 6 modules → shows 4 + `+2`
- Żabka: 5 modules → shows 4 + `+1`
- Other tenants: ≤ 4 modules, render unchanged

Verify this isn't dynamic-sized — it's literally about how many `enabled_modules` each tenant has.

### Acceptance for sub-step 1

- Buc-ee's card shows exactly 4 module pills + `+2` chip
- Żabka card shows exactly 4 module pills + `+1` chip
- Tenants with ≤ 4 modules unchanged
- `+N` chip styled consistently with module pills (token-driven)
- Tenant detail drawer still shows the complete module list (no regression)

## Sub-step 2: Type-to-confirm dialog pattern

### What it solves

Phase 4c will introduce destructive actions: Suspend Tenant, Terminate Tenant, Delete Role, Revoke User, etc. v0 stubs these as buttons that toast "Coming in v1." Tier 1 polish: build the destructive-confirm dialog component once, so 4c writes drop it in instead of inventing it ad-hoc.

The component is built but not wired to any actual destructive action yet (those still toast). One reference dialog used in `/dev/components` demo for visual verification.

### Component spec

`components/shared/ConfirmDestructive.tsx` — a wrapper around the existing shadcn `AlertDialog` primitive with a type-to-confirm requirement:

Props:
```ts
{
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string                     // e.g., "Terminate tenant"
  description: ReactNode            // body text, can include strong/code
  confirmText: string               // string user must type, e.g., "TERMINATE" or "buc-ees"
  confirmLabel: string              // button label, e.g., "Terminate tenant"
  cancelLabel?: string              // defaults to "Cancel"
  destructive?: boolean             // controls confirm button color, default true
  onConfirm: () => void | Promise<void>
}
```

Behavior:

- Dialog opens with title, description, and an input field labeled "Type {confirmText} to confirm"
- Confirm button is **disabled** until user types `confirmText` exactly (case-sensitive, trim whitespace from both sides)
- Cancel button (or Escape, or X) closes without firing onConfirm
- On confirm: calls onConfirm. If onConfirm returns a Promise, button shows loading state until resolved
- Dialog uses danger color tokens for the confirm button (red bg, white text)
- Backdrop fades, dialog scales+fades per 5.1.3 modal animations
- Reduced-motion respected (5.1.3 global rule)

### Demo wiring

Add a button to `/dev/components` page that opens a sample destructive dialog with `confirmText="DELETE"` so the visual can be verified without wiring it to any real action.

### What NOT to do in 5.1.4

- Don't wire to actual destructive actions in v0. Those stay as "Coming in v1" toasts. Phase 4c will replace the toasts with `ConfirmDestructive` invocations.
- Don't add "ARE YOU SURE? THIS CANNOT BE UNDONE" alarm copy. Trust the type-to-confirm friction.
- Don't add a countdown timer. Type-to-confirm is the friction; timing on top is overkill.

### Acceptance for sub-step 2

- `ConfirmDestructive.tsx` component created with the spec above
- Confirm button disabled until exact match typed
- Loading state during async onConfirm
- `/dev/components` demo button renders a working sample
- Component documented in PATTERNS.md (one paragraph + when to use it)

## Sub-step 3: Sidebar discoverability

### What it solves

Sidebar collapse/expand mechanism works but the trigger button (a single chevron at the bottom when collapsed) is hard to identify as "controls sidebar width." Real users miss it. The fix: tooltip + keyboard shortcut.

### Tooltip

The collapse/expand button gets a tooltip on hover:

- When sidebar is expanded: tooltip says "Collapse sidebar (⌘\)"
- When sidebar is collapsed: tooltip says "Expand sidebar (⌘\)"

Use existing shadcn Tooltip primitive (likely already in `components/ui/tooltip.tsx`). Wrap the chevron button.

Tooltip appears on hover after a brief delay (~500ms — shadcn default).

### Keyboard shortcut

`Cmd+\` (Mac) / `Ctrl+\` (Win/Linux) toggles the sidebar.

Implementation: add a global keyboard listener in `Sidebar.tsx` (or a parent component if cleaner). On the keydown event:
- Check `e.key === '\\' && (e.metaKey || e.ctrlKey)`
- Prevent default
- Call the existing `toggle()` function

The localStorage value (`ithina_sidebar_collapsed`) updates as today, so persistence is automatic.

### Visual treatment of the trigger

When sidebar is collapsed, the chevron button is a small bordered square with just a `>` icon. To improve recognizability, also:

- Slightly increase the button's contrast against the sidebar background (so it reads as interactive, not decorative)
- On hover, the button gains a more pronounced bg shift (`bg-surface-raised`) to confirm interactivity

Keep the size as today; don't make it bigger. The fix is contrast and tooltip, not enlargement.

### Acceptance for sub-step 3

- Tooltip appears on hover over the collapse/expand button
- Tooltip text correct in both states ("Collapse sidebar (⌘\)" / "Expand sidebar (⌘\)")
- `Cmd+\` toggles sidebar (Mac); `Ctrl+\` toggles (Win/Linux)
- Keyboard shortcut respects all sidebar states (works whether collapsed or expanded)
- Button hover has more pronounced bg shift than other sidebar items
- localStorage persistence unchanged (no regression)

## Sub-step 4: Roles catalog grouping

### What it solves

`/superadmin/roles` catalog tab currently renders all 15 roles in a flat scrollable list. With Platform roles (4) and Tenant roles (11) interleaved, finding a specific role requires scanning the whole list. Group them.

### Source of truth

`mocks/fixtures/roles.json` ships each role with a `scope` field that's either `PLATFORM` or `TENANT`. Use this to group, not hardcoded role names.

### Layout

In the role catalog view (likely `components/roles/RoleCatalog.tsx` or similar):

```
PLATFORM ROLES (4)
[Super Admin]
[Platform Admin]
[Module Admin]
[Support Admin]

TENANT ROLES (11)
[Owner]
[Manager]
[Pricing Manager]
[Promotions Manager]
[Inventory Manager]
[Analyst]
[Operator]
[Viewer]
[Auditor]
[Custom Role 1]
[Custom Role 2]
```

(Names approximate; use what's actually in the fixture.)

Group header: `text-label text-foreground-muted` (12px uppercase tracking-wide), with the count appended in muted weight: `PLATFORM ROLES (4)`.

Spacing: `space-y-6` between groups. Within a group, role cards keep their existing layout/spacing.

### What NOT to do

- Don't redesign the role card itself. Just group them.
- Don't add filtering/searching at this step. That's a 5.2.x consideration if needed.
- Don't change the Permission Matrix tab — that's 5.2.2 territory and explicitly out of scope.

### Acceptance for sub-step 4

- Role catalog tab shows two grouped sections: "PLATFORM ROLES (4)" and "TENANT ROLES (11)"
- Counts match fixture data (computed, not hardcoded)
- Roles within each group preserve existing order from fixture
- Group headers use `text-label` token (consistent with rest of app)
- No regression in role card rendering or click → drawer behavior

## Sub-step 5: Card density audit

### What it solves

Catch-all final pixel pass. After 5.1.1's typography sweep, 5.1.2's chip recipes, 5.1.3's animations, there will be small inconsistencies that escaped each step's specific scope. This sub-step is the cleanup.

### What to look for

Walk all 8 pages in both themes. For each, note any of these and fix:

- **Padding inconsistency** — a card with `p-3` next to cards with `p-4`, or container with `p-5` where the system says `p-6`
- **Gap inconsistency** — `gap-3` between elements where similar surfaces use `gap-4`
- **Typography deviation** — text that should use a token but uses ad-hoc `text-sm` or `text-base` directly
- **Chip recipe deviation** — a status pill that didn't get the dark/light split from 5.1.2
- **Hardcoded colors** — any remaining `text-zinc-400`, `bg-slate-800`, etc. that escaped earlier sweeps
- **Hover state missing** — an interactive row/card that doesn't have the hover pattern from 5.1.3
- **Animation duration deviation** — a transition that uses `duration-100` or `duration-300` where the system says `duration-150` or `duration-200`

### How to approach

This is the most ad-hoc sub-step. Don't write a per-page checklist. Walk the app, note specifics, fix specifics. If a fix would touch >5 files for a single inconsistency, surface before doing it (might be a system change, not a polish change).

### What NOT to do

- Don't redesign anything. This is fix-the-inconsistency, not improve-the-design.
- Don't refactor components. If a fix wants a refactor, file it; don't do it here.
- Don't expand the typography or color scale to accommodate edge cases. The scale is closed; conform to it.

### Acceptance for sub-step 5

- Walk all 8 pages in both themes documented in pre-smoke (concrete list of fixes applied)
- All fixes are ≤ 5 line changes per file (or surfaced before applying)
- No new tokens introduced
- No regressions in 5.1.1/5.1.2/5.1.3 work

## Acceptance criteria (overall)

1. Sub-step 1 acceptance met (+N overflow on Buc-ee's, Żabka)
2. Sub-step 2 acceptance met (ConfirmDestructive component + dev/components demo)
3. Sub-step 3 acceptance met (sidebar tooltip + keyboard shortcut)
4. Sub-step 4 acceptance met (Roles catalog grouped Platform/Tenant)
5. Sub-step 5 acceptance met (density audit applied)
6. The 8 pages still render with the same content and behavior
7. `pnpm tsc --noEmit` exits zero
8. `pnpm lint` exits zero
9. `pnpm build` succeeds
10. No console errors (modulo activation race; pre-mark ⚠️)
11. `prefers-reduced-motion` still respected
12. Both themes render correctly (no 5.1.2 regression)
13. BUILD_PLAN.md updated: Step 5.1.4 → DONE; Phase 5a marked complete; Phase 5b (Tier 2) entries reflect 5.2.1 (Org Tree) and 5.2.2 (permission matrix) as upcoming
14. PATTERNS.md updated with three additions: "+N overflow chip" pattern, "Type-to-confirm dialog" pattern, "Keyboard shortcut for sidebar"

## Files modified

Likely:
- `components/tenants/TenantCard.tsx` — +N module overflow
- `components/shared/ConfirmDestructive.tsx` — new file
- `app/dev/components/page.tsx` (or wherever the demo lives) — sample destructive dialog button
- `components/chrome/Sidebar.tsx` — tooltip + keyboard shortcut + button hover treatment
- `components/roles/RoleCatalog.tsx` (or wherever roles render) — grouping
- Various across `components/` for density audit findings
- `BUILD_PLAN.md`, `PATTERNS.md`

Estimated diff size: 15-30 files. Concentrated in 4 components (TenantCard, ConfirmDestructive, Sidebar, RoleCatalog) plus density-audit fixes scattered.

## Smoke checklist

After implementing:

1. **+N overflow.** Open Tenants. Buc-ee's shows 4 modules + `+2` chip. Żabka shows 4 + `+1`. Other tenants unchanged. Click Buc-ee's drawer — full module list visible.
2. **Type-to-confirm dialog.** Open `/dev/components`. Click the sample destructive button. Dialog opens with type-to-confirm input. Confirm button disabled until exact match typed. Backspace removes a char and re-disables. Type correctly → confirm enables. Click confirm → loading state → dialog closes (or whatever the demo's onConfirm does).
3. **Sidebar tooltip.** Hover the collapse/expand button. Tooltip appears with "Collapse sidebar (⌘\)" or "Expand sidebar (⌘\)" depending on state.
4. **Sidebar keyboard shortcut.** Press `Cmd+\` (Mac) or `Ctrl+\` (Win/Linux). Sidebar toggles. Repeat — toggles back. Persists across reload.
5. **Roles grouping.** Open `/superadmin/roles`. Catalog tab shows "PLATFORM ROLES (4)" with 4 roles, "TENANT ROLES (11)" with 11 roles. Counts match. Order within groups preserved from fixture.
6. **Density audit visual sweep.** Walk Dashboard → Tenants → Tenant Drawer → Provision Modal → Users → Org Tree → Roles → Modules → Guardrails → Audit Log → Notifications → Approvals. In both themes. Note anything still ad-hoc; fixes should already be in.
7. **5.1.3 animations preserved.** Click "+ Provision tenant" → modal animates in. Submit a tenant → optimistic insert lands with layout shift. Filter tabs slide.
8. **5.1.2 themes preserved.** Toggle Light → Dark → System. All surfaces render correctly.
9. **5.1.1 tokens preserved.** Typography hierarchy clear. Spacing consistent. Subtitles readable.
10. **Reduced motion preserved.** Enable in dev tools → reload. All animations instant. Type-to-confirm dialog still functional.
11. Console clean modulo activation race.
12. `pnpm build` succeeds.

## Process notes

- Pre-mark "no console errors" as ⚠️ (activation race).
- Pre-smoke self-check before browser smoke. List density-audit findings explicitly so the user can verify scope.
- Sub-steps are ordered: 1 → 2 → 3 → 4 → 5. Sub-step 5 (density audit) goes last because it's the catch-all and depends on the other four being in place.
- Don't bundle Org Tree redesign or matrix redesign work into this step. Those are 5.2.1 and 5.2.2. If during the density audit you find Org Tree or Permission Matrix surfaces are inconsistent, note for those steps — don't fix here.
- The type-to-confirm component is a forward-investment. It needs to be correct now; 30+ Phase 4c destructive actions will reference it. Spend the time to get the API right (props, async handling, accessibility).
- The sidebar keyboard shortcut needs to not conflict with anything. `Cmd+\` is unused by browsers and major web apps. Verify in your dev environment that it doesn't trigger something else (e.g., a browser extension).

## Ask before building

Things worth surfacing upfront:

- **Module sort order in TenantCard.** Confirm the existing sort order is correct ("first 4 of fixture order"), not "best 4 by some scoring." If v0 sorted modules a specific way, preserve that.
- **Type-to-confirm string casing.** Case-sensitive match? Trim whitespace? My recommendation: trim both sides, case-sensitive match. Confirm.
- **Sidebar keyboard shortcut binding.** `Cmd+\` (`Cmd+Backslash`) is the Linear/Notion convention. Confirm before binding.
- **Roles catalog grouping headers.** "PLATFORM ROLES" vs "Platform roles" vs "Platform" — confirm style. My lean: "PLATFORM ROLES (4)" all caps to match `text-label` convention.
- **Density audit scope.** If audit surfaces something that wants > 5 line changes per file, surface for go/no-go. Don't silently expand scope.

Post the pre-smoke self-check structured table when ready, same shape as v0 + 4.1 + 5.1.x steps. After smoke passes, propose the commit. Expected commit message:

> Step 5.1.4: Tier 1 polish closeout
>
> +N module overflow on tenant cards (Buc-ee's, Żabka). Type-to-confirm destructive dialog component (forward investment for Phase 4c writes). Sidebar tooltip + Cmd+\ keyboard shortcut. Roles catalog grouped Platform / Tenant. Density audit pass across all 8 pages.
>
> Closes Tier 1. Tier 2 (Org Tree redesign 5.2.1, permission matrix redesign 5.2.2) is the next polish surface.
