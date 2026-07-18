# Prompt — Step 2.3: Organization Tree

> Paste this after Step 2.2 is committed.

---

## Pre-flight

```bash
pwd
git log --oneline -5
pnpm tsc --noEmit                # zero
pnpm dev
# verify: tenants page works, drawer opens, filters work
```

Read `BUILD_PLAN.md` Step 2.3 and `Ithina_Admin_Frontend.md` section 7.3 (Organization Tree). Refer to `tenants-api-contract-v0.md` Part 2 in backend repo for the data shape.

---

## Step ID and intent

**Step 2.3** — The Organization Tree page. Two-pane layout: tenant list left with node counts, expandable tree right.

This is a CLAUDE_CODE step.

---

## Scope in

### 1. Page layout

Path: `app/superadmin/org/page.tsx`.

```
+----------------------------------------------------------------+
| PageHeader                                                     |
|   title: "Organization Tree"                                   |
|   subtitle: "Hierarchy: HQ → Region → Store → Department.      |
|              Permissions cascade down."                        |
|   primaryAction: "+ Add node"  → toasts "v1"                    |
+----------------------------------------------------------------+
| +-------------------+ +--------------------------------------+ |
| | TENANTS           | | <Selected tenant>                    | |
| | ───────────────── | | 8 nodes · 3 stores · 2 regions       | |
| | Buc-ee's      [8] | |                                      | |
| | Żabka Group   [6] | | Tree (expandable)                    | |
| | SmartStore    [3] | |   v Buc-ee's HQ (HQ, BU-HQ)          | |
| | FreshMart     [0] | |     v Texas Region (REGION, TX)      | |
| | CornerStop    [0] | |       Buc-ee's #101 (STORE, TX-101)  | |
| | GreenLeaf     [0] | |         Deli (DEPT, TX-101-DELI)     | |
| | Infomil       [0] | |       Buc-ee's #102 (STORE, TX-102)  | |
| |                   | |     v Florida Region (REGION, FL)    | |
| |                   | |       Buc-ee's #201 (STORE, FL-201)  | |
| +-------------------+ +--------------------------------------+ |
+----------------------------------------------------------------+
```

Use a CSS grid layout (`grid-cols-[280px_1fr]`) for the two panes.

### 2. Left pane: tenant list

Component: `components/org/TenantList.tsx`.

Data from `useOrgSummary()` (returns array of `{id, name, display_code, node_count}`).

Header: "TENANTS" label.

Each row:
- Tenant name
- Right-aligned: node count badge (use shadcn `Badge` with `variant="secondary"`)
- Selected state: highlighted background

Click row: selects that tenant, loads its tree on the right. Selection state via URL search param `?tenant=<id>`. Default to first tenant on initial load.

### 3. Right pane: tree

Component: `components/org/OrgTree.tsx`.

Data from `useOrgNodes(tenantId)` (returns flat list of nodes with `path`, `parent_id`, `depth`, `child_count`).

Header section above the tree:
- Tenant name (large)
- Stats line: `{node_count} nodes · {store_count} stores · {region_count} regions`

Tree rendering: take the flat list, build a parent-child map by `parent_id`, render recursively from `parent_id === null` roots.

Each tree row:
- Indent by `depth` (16px per level)
- Expand/collapse caret (only when node has children)
- Icon for node type (lucide: `Building` for HQ, `Map` for REGION, `Store` for STORE, `Building2` for BUSINESS_UNIT, `Globe` for COUNTRY, `Package` for DEPARTMENT)
- Display name in bold
- Type badge (small chip with the node_type, e.g. "HQ", "REGION")
- Code in monospace muted (e.g. "BU-HQ")
- Right-aligned: kebab menu (hidden in v0)

Click caret: toggles children visibility. Track expanded state in component-local `useState<Set<string>>` keyed by node ID. Default: all nodes expanded for v0 (so the user sees the full tree on first load; later polish can add a smarter default).

Click row body: opens node detail drawer.

### 4. Node detail drawer

Component: `components/org/NodeDetailDrawer.tsx`.

Triggered by row click. Right-side drawer.

Content:

```
+----------------------------------------+
| [Icon]  Buc-ee's HQ              [×]   |
| HQ · BU-HQ                             |
+----------------------------------------+
| PARENT                                 |
|   (root)                               |
+----------------------------------------+
| CHILDREN                               |
|   2 direct, 7 in subtree               |
+----------------------------------------+
| METADATA                               |
|   Created: 2025-05-12                  |
|   Last updated: 2025-05-12             |
|   Status: ACTIVE                       |
+----------------------------------------+
|                                        |
+----------------------------------------+
| [Edit]  [Add child]  [Delete]          |
+----------------------------------------+
```

All three buttons toast "v1".

URL state: `?tenant=<tenantId>&node=<nodeId>`.

### 5. Empty states

Two empty states per spec:

1. No tenant selected (which can't happen if we default to first, but render safely if `?tenant` is empty):
   - Title: "Select a tenant on the left"
   - Body: "Choose a tenant to view its organization."

2. Tenant has zero nodes (FreshMart, CornerStop, etc.):
   - Title: "No nodes yet"
   - Body: "Add the first node to seed this tenant's hierarchy."
   - CTA: "+ Add node" → toasts "v1"

### 6. Data hooks (verify)

Confirm `useOrgSummary()` and `useOrgNodes(tenantId)` exist and return the right shapes. If fixtures don't yet support per-tenant org trees, extend `mocks/fixtures/org-nodes.json` to have entries for at least Buc-ee's (the 8-node tree from spec) and one or two others (Żabka with ~6 nodes, SmartStore with ~3). Other tenants return `items: []`.

### 7. Loading state

Tree pane loading: render 8 row skeletons.

Tenant list loading: render 7 row skeletons.

### 8. Error state

Per pane.

---

## Scope out

- Add node modal (toast "v1")
- Edit/move/delete node operations (toast "v1")
- Drag-and-drop (deferred)
- Lazy-loading subtree (full tree fetched at once for v0)
- Permissions view per node ("View permissions" kebab item)
- Path search within tree

---

## Acceptance criteria

1. `/superadmin/org` renders two-pane layout
2. Tenant list shows all 7 tenants with node counts; selected state highlights
3. First tenant auto-selected on initial load
4. Selecting a tenant updates URL and loads its tree
5. Tree renders Buc-ee's hierarchy correctly: HQ at root, 2 regions under HQ, stores under regions, departments under stores
6. Expand/collapse carets work
7. Node icons match node type
8. Click node row opens detail drawer
9. Drawer shows parent, children counts, metadata; action buttons toast "v1"
10. URL state for tenant + node works (reload restores)
11. Empty states render for tenants with zero nodes
12. `pnpm tsc --noEmit` exits zero
13. No console errors
14. `BUILD_PLAN.md` Step 2.3 flipped to DONE

---

## After completing the step

1. Confirm acceptance
2. Report any fixture additions
3. Flag tree-rendering decisions (default expansion, indent size, etc.)
4. Update BUILD_PLAN.md
5. Propose commit:
   ```
   git add -A
   git commit -m "Step 2.3: Org Tree page with two-pane layout, expandable tree, node drawer"
   ```
6. Wait before Step 2.4

---

## If you hit a snag

- Building the parent-child tree from a flat list: extract a small helper `lib/utils/build-tree.ts` that takes the flat array and returns a nested structure. Test with Buc-ee's fixture data.
- Recursive component vs iterative render: a recursive component (each node renders itself + a list of `<TreeNode>` for each child) is simpler. Don't over-engineer.
- Path display vs ltree path: the spec says nodes have an `ltree` path like `bu_hq.tx.tx_101`. Render it in the drawer if useful, but the visual hierarchy already conveys it. Don't surface it in the row.
