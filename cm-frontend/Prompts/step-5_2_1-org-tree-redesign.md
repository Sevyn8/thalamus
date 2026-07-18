# Step 5.2.1 — Org Tree Redesign

## Context and intent

5.1.1-5.1.4 closed Tier 1 polish. The build feels deliberate and alive across all surfaces except two pages flagged as "structurally rough" during demo: Org Tree (this step) and Permission Matrix (5.2.2).

User's diagnosis on Org Tree: "the tree itself looks like a flat list, hierarchy isn't visually clear." v0 shipped the spec'd two-column layout (TENANTS list + tree) but the tree-side rendering relies on indentation alone — no indent guide lines, missing or weak type icons, default-collapsed state hiding most of the structure on load. The hierarchy is *technically* visible but not *visually* obvious.

This step rebuilds the tree component to make hierarchy unambiguous. Reference vibe: **Linear / VS Code**. Compact rows, indent guide lines connecting parents to children, type-specific icons, type badges, two levels auto-expanded by default. Custom build using shadcn primitives + recursive rendering — no tree library dependency.

Out of scope: Permission Matrix redesign (5.2.2), tree search/filter (defer), drag-and-drop reorder (Phase 4c Move workflow), node detail drawer redesign (already shipped, keep unless audit finds rough).

## Aesthetic anchor: Linear / VS Code-style nested tree

Concrete reference points:

- **Indentation:** 16px per level. Each child sits 16px right of its parent.
- **Indent guides:** vertical 1px line in `var(--border)` at each ancestor's indentation level. Lines connect from one row's expand caret area down through descendants. Visually identical to VS Code's file explorer or Linear's project hierarchy.
- **Row height:** ~32px. Compact, scan-friendly. Not "data table dense" (~28px) — interactive tree wants slightly more breathing room.
- **Expand/collapse caret:** chevron-right (collapsed) / chevron-down (expanded). 16px square click target. Sits at the row's left edge after indentation. If a node has no children, render a 16px spacer instead — keeps icons aligned across rows regardless of expand state.
- **Type icon:** 16px lucide-react icon, color-tinted by node type. Sits immediately right of the caret/spacer.
- **Display name:** `text-body` weight, default foreground color.
- **Type badge:** small chip (~18px tall) with type name uppercased, e.g., `HQ`, `REGION`, `STORE`. Token-driven chip recipe (matches existing `Chips.tsx` patterns).
- **Code:** `text-secondary text-foreground-muted` font-mono. Sits at the right edge of the row.
- **Kebab menu:** appears on row hover at the far right, between code and row edge. Standard MoreHorizontal icon, opens dropdown with Edit / Move / Delete / View permissions / Copy code.

## Acceptance criteria

1. **Tree renders with indent guides.** Each level shows a 16px indentation. Vertical guide lines run through ancestor columns, visually connecting parent to children.
2. **Default expansion: two levels.** When a tenant is selected, the tree opens with TENANT root + first level (BUSINESS_UNIT or HQ) auto-expanded, plus the second level under those. Subsequent levels collapsed; user clicks to expand.
3. **Type icons present.** Each row shows a node-type icon. Mapping (use lucide-react):
   - `TENANT` → `Building2`
   - `BUSINESS_UNIT` → `Briefcase`
   - `HQ` → `Landmark`
   - `COUNTRY` → `Globe`
   - `REGION` → `MapPin`
   - `STORE` → `Store`
   - `DEPARTMENT` → `Folder`
   Icons are 16px, color-tinted to match the type's chip recipe (subtle — primary color is the chip; icon is supporting).
4. **Type badges present.** Each row shows a small uppercase badge (`HQ`, `REGION`, `STORE`, etc.) using the existing chip recipe family. Tone-per-type mapping:
   - `TENANT` → blue
   - `BUSINESS_UNIT` → violet
   - `HQ` → blue
   - `COUNTRY` → teal
   - `REGION` → emerald
   - `STORE` → amber
   - `DEPARTMENT` → grey
   Reuse `Chips.tsx` infrastructure; add a new `OrgNodeTypeChip` variant if needed.
5. **Code rendered in muted monospace.** Right-aligned per row, `font-mono text-secondary text-foreground-muted`.
6. **Caret expands/collapses on click.** Click on the chevron toggles children inline. No animation regression — children appear/disappear via the existing tw-animate-css fade pattern (or a subtle `accordion-down` keyframe if cleaner).
7. **Row body click opens drawer.** Click anywhere on the row except the caret/kebab opens the existing node detail drawer (`NodeDetailDrawer.tsx` or whatever v0 named it). No drawer redesign.
8. **Kebab menu on row hover.** Standard 5-option menu: Edit, Move, Delete, View permissions, Copy code. v0 may have these stubbed as toasts; preserve that behavior. Phase 4c will wire the writes.
9. **Stat line above tree.** Header shows "{name} · {n} nodes · {m} stores · {r} regions" — computed from the tree data, not hardcoded. Position: top of right column, above the tree itself.
10. **Empty state preserved.** When no tenant is selected, right column shows "Select a tenant on the left to view its organisation." (v0 already has this; verify and keep.)
11. **Two-column layout preserved.** Left TENANTS list with node-count badges (already in v0); right tree (this step's redesign target). No changes to the left column unless an inconsistency surfaces during the work.
12. **Buc-ee's renders correctly.** Per the seed data, Buc-ee's tree includes: Tenant root → HQ → multiple regions → multiple stores. With two-level auto-expansion, opening Buc-ee's should immediately show Tenant + HQ visible, and HQ's regions visible. Stores collapsed under regions.
13. **Reduced motion respected.** Expand/collapse animation degrades gracefully under `prefers-reduced-motion`.
14. The 8 pages still render with the same content and behavior. Org Tree is the only redesigned page.
15. `pnpm tsc --noEmit` exits zero.
16. `pnpm lint` exits zero.
17. `pnpm build` succeeds.
18. No console errors (modulo activation race; pre-mark ⚠️).
19. BUILD_PLAN.md updated: Step 5.2.1 → DONE; Phase 5b entry shows 5.2.1 done, 5.2.2 remaining.
20. PATTERNS.md updated with "Org Tree component" section: structure, indent-guide pattern, default expansion strategy, how to extend.

## Component structure

Build (or rebuild) these components:

### `components/org/OrgTree.tsx`

Top-level component for the right column. Props:
```ts
{
  tenant: Tenant
  nodes: OrgNode[]      // flat list, each with parent_id
  onNodeClick: (node: OrgNode) => void  // opens drawer
  onNodeAction: (node: OrgNode, action: 'edit' | 'move' | 'delete' | 'view-permissions' | 'copy-code') => void
}
```

Internally:
- Build tree from flat list (`nodes.filter(n => n.parent_id === root.id)`, recursive)
- Compute stat line (`nodes.length`, count by type)
- Render header (name + stat line) + recursive `<OrgTreeNode />` rows
- Manage expansion state (Map<nodeId, boolean>) initialized to two-levels-deep

### `components/org/OrgTreeNode.tsx`

Single tree row. Props:
```ts
{
  node: OrgNode
  depth: number          // for indentation
  hasChildren: boolean
  isExpanded: boolean
  ancestorGuides: boolean[]  // [true, false, true] = lines at depths 0, 2; spacer at depth 1
  onToggle: () => void
  onClick: () => void
  onAction: (action: ...) => void
  children: React.ReactNode  // child nodes if expanded
}
```

Renders: indent guides (one column per ancestor) + caret/spacer + icon + name + badge + code + kebab.

### Indent guide rendering

The hardest visual detail. Each row's left edge is a sequence of 16px-wide columns, one per ancestor depth level. Each column either:
- Contains a 1px vertical line (`bg-border`) — if this ancestor has more siblings below the current row's lineage
- Is empty — if the lineage from this ancestor has terminated above the current row

This is the "L-shaped tracking" effect that makes VS Code's file tree readable. Implementation: each row receives an `ancestorGuides: boolean[]` prop computed by the parent. For each `true`, render a 16px-wide div with `border-l border-border h-full`.

For the row's own depth column (the last one before the caret), if the row has siblings *below it*, the guide continues; if it's the last child, the guide stops at the caret (visually creating an L). This requires knowing "is this the last child of its parent" — pass as a separate `isLastChild: boolean` prop and render a special "L-corner" guide for the last column.

If this proves too fiddly, ship a simpler version: solid vertical lines through all ancestor columns, no L-corner. Less polished but readable. Surface for go/no-go before committing.

### `components/org/OrgNodeTypeBadge.tsx`

Small chip showing the node type. Reuses `Chips.tsx` recipe family. Tone per-type per the mapping above.

### `components/org/OrgNodeTypeIcon.tsx`

Lucide icon mapped per type. Color-tinted matching the badge tone but more muted (icon shouldn't compete with badge for attention).

## Page integration

`app/(authenticated)/superadmin/org/page.tsx` — the Org Tree page itself:
- Verify two-column layout still in place (left TENANTS list, right tree area)
- Replace whatever v0 renders in the right column with `<OrgTree />`
- Wire `onNodeClick` to open the existing drawer
- Wire `onNodeAction` to whatever v0 stubs (likely toasts — preserve)

If the URL param routing (`?tenant={tenantId}` and possibly `?node={nodeId}`) is already wired, leave alone. If not, surface — but probably out of scope for this step.

## Default expansion logic

On tenant select (or initial load if URL has tenant param):
1. Find the TENANT root node (parent_id === null, node_type === 'TENANT')
2. Mark it expanded
3. For each direct child of root (depth 1): mark expanded
4. For each grandchild (depth 2): leave default (collapsed)

Result: user sees Tenant → first-level children → second-level children. Past depth 2, click to expand.

State management: `useState<Set<string>>(initialExpansion)`. `toggle(nodeId)` adds/removes from the set.

## Animation behavior

Expand/collapse: children fade in over 150ms when expanding; fade out over 100ms when collapsing. Same easing tokens as 5.1.3 (`var(--ease-out)`, `var(--ease-in)`).

Implementation: wrap children in a div with `data-[expanded=true]:animate-in data-[expanded=false]:animate-out fade-in-0 fade-out-0 duration-150`. Or use Framer Motion's AnimatePresence if cleaner; the codebase already has Framer for the optimistic-insert pattern.

For a tree with 100 stores under a region, the expand should still feel fast — don't stagger the children's animation by index, just fade the whole subtree in/out.

Reduced motion: rely on global rule from 5.1.3. Under reduced motion, children appear/disappear instantly.

## Files modified

Likely:
- `components/org/OrgTree.tsx` — rewrite (new component)
- `components/org/OrgTreeNode.tsx` — rewrite or new
- `components/org/OrgNodeTypeBadge.tsx` — new (or extend `Chips.tsx`)
- `components/org/OrgNodeTypeIcon.tsx` — new
- `app/(authenticated)/superadmin/org/page.tsx` — integration
- `components/shared/Chips.tsx` — possibly extend with the type chip variant (if not extending an existing chip family)
- `BUILD_PLAN.md`, `PATTERNS.md`

Files to leave alone:
- The left-column TENANTS list (already shipped, presumably fine)
- `NodeDetailDrawer.tsx` (drawer is out of scope)
- The mock data in `mocks/fixtures/org-nodes.json` (presumably already shaped for this step)

Estimated diff: 6-12 files. Mostly concentrated in 4-5 new/rewritten components.

## Smoke checklist

After implementing:

1. **Open `/superadmin/org`.** Two-column layout still in place: left TENANTS list with counts, right empty state.
2. **Click Buc-ee's in the left list.** Right column shows "Buc-ee's · {n} nodes · {m} stores · {r} regions" header. Tree below shows Tenant root + HQ + regions visible immediately. Stores collapsed.
3. **Visual hierarchy clarity.** Indent guides visible. Icons distinct per type. Type badges color-coded. Codes muted on the right. The page reads as a tree, not a flat list.
4. **Click a region's caret.** Children (stores) fade in, expand state updates. Click again — collapse.
5. **Click a region row body.** Drawer opens with that region's detail.
6. **Hover a row.** Kebab appears at far right. Click kebab — dropdown with Edit/Move/Delete/View permissions/Copy code. Click Edit — toast or modal (whatever v0 had).
7. **Click another tenant in left list.** Tree resets. New tenant's tree renders with two-level expansion fresh.
8. **Click an empty-tree tenant** (e.g., a tenant with only a Tenant root + 1 HQ node). Tree renders correctly without errors. Caret behavior works on minimal trees.
9. **Reduced motion check.** Enable in dev tools → reload → expand/collapse should be instant. Tree still functional.
10. **Both themes still render.** Toggle Light → Dark via profile menu. Tree colors, indent guides, type badges all readable in both.
11. **Other 7 pages unaffected.** Walk Dashboard → Tenants → Users → Roles → Modules → Guardrails → Audit. No regression.
12. Console clean modulo activation race.
13. `pnpm build` succeeds.

## Process notes

- Pre-mark "no console errors" as ⚠️ (activation race).
- Pre-smoke self-check before browser smoke. Verify two-level expansion works for tenants with varying tree depths (e.g., a tenant with only Tenant + HQ should still render correctly).
- The L-corner indent guide detail is the polish risk. Ship a simpler all-vertical-lines version first; iterate to L-corners if browser smoke shows the simpler version reads as ambiguous. Don't over-engineer this on first pass.
- The type icon + type badge double-encoding (both visible per row) is intentional — icon for fast-scan visual identification, badge for unambiguous text labeling. Don't drop one in favor of the other to "reduce visual noise" — they serve different cognitive jobs.
- If the seed data has surprising shape (e.g., a tenant with no HQ between TENANT and REGION), the tree must render gracefully. Don't assume hierarchy levels are always present — the spec explicitly notes "Not every level must be present in every tenant, but parent-child ordering must respect this sequence."
- `prefers-reduced-motion` is global rule from 5.1.3 — animations degrade automatically. Don't add per-component reduced-motion logic.

## Ask before building

Things worth surfacing upfront:

- **Existing v0 component names.** What does v0 call the current tree component? `OrgTree.tsx`, `OrgTreeView.tsx`, something else? Need this for accurate "rewrite" vs "new" framing in the diff.
- **Existing seed data shape.** Open `mocks/fixtures/org-nodes.json` (or wherever org nodes live). How many nodes does Buc-ee's have? Does the seed cover all 7 node types or just some? If the seed is sparse (e.g., only Tenant + HQ + Stores, no Regions or Departments), the type-icon-and-badge work still ships but the visual variety is limited — flag for richer seed data in a future step.
- **Drawer existence.** Is `NodeDetailDrawer` already shipped in v0? If yes, `onNodeClick` wires to it; if no, surface — Phase 4c may need to build it, but this step shouldn't.
- **Kebab actions current behavior.** Edit/Move/Delete/View permissions/Copy code — do these toast in v0, or are they wired to anything? Either way is fine; need to know the current behavior to preserve.
- **L-corner guides vs simpler vertical lines.** Confirm before shipping. Simpler version is faster but slightly less polished. L-corners match VS Code precisely but require careful "is-last-child" computation.

Post the pre-smoke self-check structured table when ready, same shape as v0 + 4.1 + 5.1.x steps. After smoke passes, propose the commit. Expected commit message:

> Step 5.2.1: Org Tree redesign
>
> Rebuild tree component for visual hierarchy clarity. Linear/VS Code-style: indentation per level, indent guide lines connecting parents to children, type-specific lucide icons, type badges color-coded per node type, monospace muted code. Default expansion shows first two levels.
>
> Custom build, no tree library dependency. Reuses Chips.tsx infrastructure for type badges, lucide-react for icons.
>
> Tier 2 begins. 5.2.2 (permission matrix grouping) remains.
