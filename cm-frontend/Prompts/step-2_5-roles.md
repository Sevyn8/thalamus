# Prompt — Step 2.5: Roles & Permissions

> Paste this after Step 2.4 is committed.

---

## Pre-flight

```bash
pwd
git log --oneline -5
pnpm tsc --noEmit                # zero
pnpm dev
```

Read `BUILD_PLAN.md` Step 2.5, `Ithina_Admin_Frontend.md` section 7.5, and `tenants-api-contract-v0.md` Part 6.

---

## Step ID and intent

**Step 2.5** — The Roles & Permissions page. Two tabs: Role catalog (default) and Permission matrix.

This is a CLAUDE_CODE step.

---

## Scope in

### 1. Page layout

Path: `app/superadmin/roles/page.tsx`.

```
+----------------------------------------------------------------+
| PageHeader                                                     |
|   title: "Roles & Permissions"                                 |
|   subtitle: "Permission = Module + Resource + Action + Scope"  |
|   primaryAction: "+ Custom role"  → toasts "v1"                 |
+----------------------------------------------------------------+
| Tabs: [Role catalog] [Permission matrix]                       |
+----------------------------------------------------------------+
| (tab content)                                                  |
+----------------------------------------------------------------+
```

Use shadcn `Tabs`. Default `catalog`. Tab state via URL: `?tab=catalog` or `?tab=matrix`.

### 2. Role catalog tab

Component: `components/roles/RoleCatalogView.tsx`.

Two columns:

**Left: role list grouped**

```
PLATFORM ROLES
  [crown] Super Admin              4
  [crown] Platform Admin           7
  [crown] Module Admin             12
  [crown] Support Admin            18

TENANT ROLES
  [user]  Owner                    9
  [user]  Pricing Manager          34
  [user]  Category Manager         52
  [user]  Merchandising            78
  [user]  Marketing                41
  [user]  Store Operations         184
  [user]  Store Manager            ...
  [user]  Associate                ...
  [user]  Night Shift Lead         ...
  [user]  Finance                  ...
  [user]  IT / Analytics           ...
```

Each row: icon (crown for platform, user for tenant), role name, user count below. Selected row highlighted.

Click row: updates right pane.

**Right: role detail**

```
+--------------------------------------------------+
| [PLATFORM ROLE]   Super Admin           [Edit] [Delete] |
| Full platform control. Reserved for...           |
| 4 users assigned                                  |
+--------------------------------------------------+
| PERMISSIONS (24)                                 |
| Pricing OS > Pricing Rules    [VIEW]     [Tenant] |
| Pricing OS > Pricing Rules    [CONFIGURE][Tenant] |
| Pricing OS > Markdowns        [EXECUTE]  [Store]  |
| ...                                              |
+--------------------------------------------------+
```

`Edit` and `Delete` buttons toast "v1". `Delete` is disabled when role is built-in or has users assigned (per spec); show a tooltip explaining why.

Permissions list: each row shows `<Module> > <Resource>`, action chip (colour-coded per `Chips.tsx`), scope chip on the right.

Default selection: first role in the list (Super Admin).

Selection state via URL: `?role=<id>`.

### 3. Permission matrix tab

Component: `components/roles/PermissionMatrixView.tsx`.

Wide grid:

- First column: permission rows. Each row shows resource name in bold, sub-row `<Module> · <ACTION> · <Scope>`.
- Header row: every role across the platform, abbreviated names rotated 45° or stacked vertically (whichever fits)
- Cell: checkbox indicating whether that role grants that permission

For v0:
- Cells are READ-ONLY. No save button, no edit mode. (Spec describes batched edit; deferred to v1 wiring.)
- Permissions sourced from `usePermissions()` (returns ~30 permissions)
- Roles sourced from `useRoles()` (returns ~15 roles)
- Cross-reference: each `Role` has a `permission_ids: string[]` field (or similar). Use that to mark cells.

If your fixtures don't have the permission_ids on roles yet, extend `mocks/fixtures/roles.json` to include the cross-reference. Pick reasonable assignments matching the spec table (e.g., Super Admin gets all permissions; Pricing Manager gets Pricing OS permissions; etc.).

Visual: grid is wide (15+ columns). Use `overflow-x-auto` on a wrapping div. Sticky first column for scrolling.

### 4. Data hooks

Confirm `useRoles()`, `useRole(id)`, `usePermissions()` exist with appropriate shapes.

For v0: load all roles and all permissions on mount; the matrix doesn't paginate.

### 5. Empty states

Roles & Permissions never empty (built-in roles always present per spec).

### 6. Loading

Catalog: skeleton list + skeleton detail panel.
Matrix: skeleton grid.

---

## Scope out

- Custom role modal (toast "v1")
- Edit role flow (toast "v1")
- Delete role flow (toast "v1")
- 4-step permission picker (Module → Resource → Action → Scope)
- Matrix edit mode with batched save
- Role hierarchy (out of v1 per backend)
- Per-user permission overrides

---

## Acceptance criteria

1. `/superadmin/roles` renders with `catalog` tab default
2. Tab switching works; URL updates `?tab=catalog|matrix`
3. Catalog tab: roles grouped PLATFORM / TENANT with user counts and crown/user icons
4. Selecting a role updates right pane; URL updates `?role=<id>`
5. Right pane shows role details + permissions list with action chips colour-coded and scope chips
6. "Edit" / "Delete" buttons toast "v1"; Delete disabled with tooltip for built-in or in-use roles
7. Matrix tab: grid renders with permissions as rows and roles as columns, checkboxes show current grants
8. Matrix is read-only (cells don't toggle in v0)
9. "+ Custom role" toasts "v1"
10. `pnpm tsc --noEmit` exits zero
11. No console errors
12. BUILD_PLAN.md Step 2.5 flipped to DONE

---

## After completing the step

1. Confirm
2. Report fixture extensions (you'll likely add `permission_ids` to roles)
3. Flag any matrix layout decisions (rotated headers, sticky first column, etc.)
4. Update BUILD_PLAN.md
5. Propose commit:
   ```
   git add -A
   git commit -m "Step 2.5: Roles & Permissions with catalog and matrix views"
   ```
6. Wait before Step 2.6

---

## If you hit a snag

- Matrix sizing: at 15 roles × 30 permissions = 450 cells. Render fine in DOM. Don't try to virtualise.
- Action chip colours from spec: VIEW grey, CONFIGURE blue, EXECUTE teal, APPROVE green, OVERRIDE red, AUDIT purple.
- Counting users per role: pull from fixture role data (each role has a `user_count` field per the contract).
- Vertical text in matrix headers: CSS `writing-mode: vertical-rl` or `transform: rotate(-45deg)` on text. Or stacked text "S\nU\nP\nE\nR" — ugly. Pick the rotation; it's better than truncated horizontal text.
