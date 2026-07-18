# Prompt — Step 1.4: Chrome (layout shell)

> Paste this after Step 1.3 is committed.

---

## Pre-flight

```bash
pwd
git log --oneline -5             # Step 1.3 commit at top
pnpm tsc --noEmit                # zero
pnpm dev
# verify: /dev/login → pick persona → /superadmin/dashboard shows "Dashboard — 7 tenants loaded"
```

If the data plane from Step 1.3 isn't working, STOP.

Read `BUILD_PLAN.md` Step 1.4 and the `Ithina_Admin_Frontend.md` sections 4.2 (Persistent chrome) and 4.3 (Navigation rules) to understand what the chrome must contain. The frontend spec is in the backend repo's project files; you have notes from the bootstrap context.

---

## Step ID and intent

**Step 1.4** — Sidebar and top bar present on every authenticated page. The chrome that wraps every `/superadmin/*` route.

This is a CLAUDE_CODE step. After this step, every `/superadmin/*` page renders inside the chrome. Active nav highlights based on pathname. Profile menu opens. The dashboard placeholder from 1.3 still works.

---

## Scope in

### 1. Layout file

Create `app/superadmin/layout.tsx` that wraps all `/superadmin/*` children. Server component, reads current user from JWT for the top-bar avatar.

```
+-------------+--------------------------------------------------+
| Sidebar     | Top bar                                          |
|             +--------------------------------------------------+
|             |                                                  |
|             |  Main content slot (children)                    |
|             |                                                  |
|             |                                                  |
+-------------+--------------------------------------------------+
```

Fixed sidebar (240px wide expanded, 64px collapsed). Sticky top bar. Main content scrolls.

### 2. Sidebar (`components/chrome/Sidebar.tsx`)

Brand mark at top (text "Ithina" + small logo placeholder), label "SUPERADMIN CONSOLE" below.

Then 4 nav groups in this exact order:

```
OVERVIEW
  Platform Dashboard       /superadmin/dashboard

GOVERNANCE
  Tenants                  /superadmin/tenants
  Organization Tree        /superadmin/org
  Users                    /superadmin/users

ACCESS CONTROL
  Roles & Permissions      /superadmin/roles
  Module Access            /superadmin/modules
  Guardrails               /superadmin/guardrails

COMPLIANCE
  Audit Log                /superadmin/audit
```

Each nav item has:

- Icon (from lucide-react: `LayoutDashboard`, `Building2`, `Network`, `Users`, `Shield`, `Boxes`, `AlertTriangle`, `FileText` — pick reasonable matches)
- Label
- Active state: pathname matches → highlight (background tint, text colour shift)
- Hover state: subtle background tint

Group headers are uppercase, smaller, muted colour, and not clickable.

At the bottom of the sidebar: collapse toggle button. When collapsed, only icons show (labels hidden), brand mark shrinks.

Use `usePathname()` from `next/navigation` to detect active route. Use a client component for the active-state logic.

Collapse state: persist in `localStorage` under key `ithina_sidebar_collapsed`. Default expanded.

### 3. Top bar (`components/chrome/TopBar.tsx`)

Left side:
- `PLATFORM` pill (small badge, no behaviour in v0)
- Breadcrumb text: "Ithina · Superadmin Governance Console"

Right side (in this order, left to right):
- Global search input with placeholder "Search tenants, users, roles..." (no behaviour in v0; just renders)
- Notifications bell button with unread count badge (placeholder "3" in v0)
- User avatar with profile menu

Notifications bell click opens a popover (use shadcn `DropdownMenu` or a `Popover`). Renders 3-4 mock items in v0 with title, body, timestamp. No real data.

User avatar is a circle with the user's initials. Click opens a popover:

- User name (bold)
- Role label (e.g. "Super Admin")
- Separator
- Profile (link to `/profile`)
- Theme (placeholder, no behaviour)
- Help (placeholder, no behaviour)
- Separator
- Log out (clears the dev cookie, redirects to `/dev/login`)

Use the `getCurrentUser()` from `lib/auth/client.ts` to get the persona. This is a client component since it needs interactivity.

### 4. Impersonation banner (`components/chrome/ImpersonationBanner.tsx`)

Sticky at the very top of every page (above top bar) when impersonation is active. v0 doesn't have real impersonation state; render the banner only when a query param `?impersonating=true` is present (dev affordance for testing the banner).

Banner content (per spec section 8.4):

```
You are impersonating <user> (<role>) for ticket <ref>. <time-remaining>. End session.
```

High-contrast orange background, white text. "End session" is a button that, in v0, just removes the query param and reloads.

### 5. Theme palette

The prototype uses Ithina-branded colours. For v0 shell, do not pixel-match. Set CSS variables in `app/globals.css` using shadcn's variable system, but pick values close to the prototype's dark theme:

- Background: deep slate / near-black
- Card / panel: slightly lighter slate
- Primary accent: Ithina blue (a teal-leaning blue, around `#3b82f6` to `#06b6d4`)
- Success / active: green
- Warning / trial: amber
- Danger / suspended / denied: red

These are placeholders; the polish pass tunes them. Document in a comment that exact hex values come later.

### 6. Update placeholder pages

Create empty placeholder pages for each of the 8 routes so the sidebar links work:

- `app/superadmin/dashboard/page.tsx` (already exists from Step 1.3 — keep it)
- `app/superadmin/tenants/page.tsx`
- `app/superadmin/org/page.tsx`
- `app/superadmin/users/page.tsx`
- `app/superadmin/roles/page.tsx`
- `app/superadmin/modules/page.tsx`
- `app/superadmin/guardrails/page.tsx`
- `app/superadmin/audit/page.tsx`

Each placeholder renders just `<h1>` with the page name. Real content comes in Phase 2.

### 7. Profile page placeholder

Create `app/profile/page.tsx` (NOT under `/superadmin`) that renders the current user's name, email, role, and tenant. Read-only. Use `getCurrentUser()` server-side.

---

## Scope out

- Pixel-exact colour matching (deferred polish pass)
- Real notifications data (handler exists from 1.3 with mock items; surface them in the popover but don't try to make the bell trigger real updates)
- Real global search (the input renders; submit does nothing)
- Theme toggle behaviour (button exists, no-op)
- Real impersonation logic
- Localisation
- Animation polish on collapse, popover open/close (basic shadcn defaults are fine)

---

## Acceptance criteria

1. Visiting any `/superadmin/*` route shows sidebar + top bar wrapping the page content
2. All 8 sidebar links navigate correctly
3. Active link highlights based on pathname
4. Sidebar collapse toggles between expanded and collapsed; state persists across page navigation
5. Profile menu opens with name, role, profile link, log out
6. Log out clears cookie and redirects to `/dev/login`
7. Notifications bell opens popover with 3-4 mock items
8. Adding `?impersonating=true` to any URL shows the orange banner above the chrome; "End session" removes it
9. `/profile` shows the current persona's read-only details
10. `pnpm tsc --noEmit` exits zero
11. No console errors
12. `BUILD_PLAN.md` Step 1.4 flipped to DONE

---

## After completing the step

1. Confirm acceptance
2. Report:
   - Files added (with line counts)
   - Any sidebar/top-bar choices that diverged from the prototype (icon picks, ordering, etc.)
   - Decisions about the colour palette
3. Update BUILD_PLAN.md
4. Propose commit:
   ```
   git add -A
   git commit -m "Step 1.4: chrome layout shell with sidebar, top bar, profile menu"
   ```
5. Wait for user direction before Step 1.5

---

## If you hit a snag

- shadcn primitive doesn't quite fit (e.g., notifications popover): use `DropdownMenu` for menu-style, `Popover` for richer content. Don't fight the library; pick the closer primitive.
- Active nav highlight doesn't work because layout is server but pathname needs client: extract the active-state logic into a small client component (`<NavLink>`) used inside the sidebar. Server component renders the layout; client component handles the active state per link.
- Banner z-index conflicts with sticky top bar: stack with explicit `z-` values. Banner above top bar, top bar above content.
