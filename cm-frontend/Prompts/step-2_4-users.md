# Prompt — Step 2.4: Users page

> Paste this after Step 2.3 is committed.

---

## Pre-flight

```bash
pwd
git log --oneline -5
pnpm tsc --noEmit                # zero
pnpm dev
```

Read `BUILD_PLAN.md` Step 2.4, `Ithina_Admin_Frontend.md` section 7.4 (Users), and `tenants-api-contract-v0.md` Part 3.

---

## Step ID and intent

**Step 2.4** — The Users page. Unified table mixing platform users and tenant users.

This is a CLAUDE_CODE step.

---

## Scope in

### 1. Page layout

Path: `app/superadmin/users/page.tsx`.

```
+----------------------------------------------------------------+
| PageHeader                                                     |
|   title: "Users"                                               |
|   subtitle: "{n} visible users · multi-tenant assignment with  |
|              role-based access"                                |
|   primaryAction: "+ Invite user"  → toasts "v1"                 |
+----------------------------------------------------------------+
| Search input                       Tenant filter dropdown      |
+----------------------------------------------------------------+
| Table                                                          |
| | USER | TENANT | ROLES | LOCATIONS | STATUS | MFA | LAST ACT | |
+----------------------------------------------------------------+
```

### 2. Filters

Search: input, debounced 300ms, sets `?search=...`. Filters by name and email.

Tenant dropdown: shadcn `Select`. Options:
- "All tenants" (default, no filter)
- "Platform (Ithina)" (audience=PLATFORM)
- One option per tenant from `useTenants()` (audience=TENANT, tenant_id=<id>)

URL state: `?audience=PLATFORM` or `?tenant_id=<uuid>`.

### 3. Table

Component: `components/users/UsersTable.tsx`.

Use shadcn `Table`. Columns:

1. USER: avatar (initials, coloured), name (bold), email (muted)
2. TENANT: tenant name, or "Platform (Ithina)" for platform users
3. ROLES: row of role chips. Multiple chips if user has multiple roles. Wrap.
4. LOCATIONS: text count "1 location" / "2 locations" / em-dash for none
5. STATUS: status chip (`ACTIVE`, `INVITED`, `SUSPENDED`)
6. MFA: small dot indicator — green dot + "On" if `mfa_enabled`, red dot + "Off" otherwise
7. LAST ACTIVE: relative time via `date-fns formatDistanceToNow` (e.g. "2 min ago", "1 day ago"); em-dash if null
8. (kebab column hidden in v0)

Row click: opens user detail drawer.

Use the 17 fixture users from Appendix E demo data.

### 4. User detail drawer

Component: `components/users/UserDetailDrawer.tsx`.

Right-side drawer triggered from row click.

Content:

```
+----------------------------------------+
| [Avatar AM]  Anjali Mehta         [×]  |
| anjali@ithina.ai                       |
| Platform (Ithina)                      |
+----------------------------------------+
| STATUS    MFA           LAST ACTIVE    |
| Active    On            2 min ago      |
+----------------------------------------+
| ROLES (1)                              |
| [Super Admin]                          |
+----------------------------------------+
| LOCATIONS (0)                          |
| —                                      |
+----------------------------------------+
| RECENT ACTIVITY                        |
| (last 10 audit events as actor)        |
| - Enabled module ROOS for Buc-ee's     |
| - ...                                  |
+----------------------------------------+
|                                        |
+----------------------------------------+
| [Edit] [Suspend] [Reset MFA] [Impers.] |
+----------------------------------------+
```

Action buttons:

- "Edit" → toasts "v1"
- "Suspend" / "Reactivate" (depending on current status) → toasts "v1"
- "Reset MFA" → toasts "v1"
- "Resend invitation" (only when status === INVITED) → toasts "v1"
- "Impersonate" (only when current persona is SUPER_ADMIN or SUPPORT_ADMIN, AND target is not also SUPER_ADMIN/SUPPORT_ADMIN) → toasts "v1"

Recent activity: pull from `useAuditLogs({ actor_user_id: user.id, limit: 10 })`. If hook doesn't support this filter yet, extend the handler.

### 5. URL state

`?user=<id>` opens drawer. Reload restores.

### 6. Empty state

Filters yield zero users:
- Title: "No users match your filter"
- Body: "Try a different search or tenant."

### 7. Loading

10 row skeletons.

### 8. Error

Per-section.

---

## Scope out

- Invite modal (toast "v1")
- Edit modal
- Suspend / reactivate / reset MFA / resend invite / impersonate flows (toast "v1")
- Manage roles modal
- Multi-tenant user assignment UX (open question; v0 shows one tenant per user)

---

## Acceptance criteria

1. `/superadmin/users` renders all 17 fixture users in a table
2. Subtitle shows correct count
3. Search filters by name/email; URL updates
4. Tenant filter narrows table; URL updates
5. "+ Invite user" toasts "v1"
6. Row click opens drawer with user details and recent activity
7. Drawer action buttons render correctly per status (Resend invite hidden for non-INVITED, Impersonate hidden when not permitted, Reactivate vs Suspend toggles by status)
8. All drawer actions toast "v1"
9. Empty state renders when filters yield zero
10. `pnpm tsc --noEmit` exits zero
11. No console errors
12. BUILD_PLAN.md Step 2.4 flipped to DONE

---

## After completing the step

1. Confirm acceptance
2. Report
3. Update BUILD_PLAN.md
4. Propose commit:
   ```
   git add -A
   git commit -m "Step 2.4: Users page with unified table, filters, detail drawer"
   ```
5. Wait before Step 2.5

---

## If you hit a snag

- 17 users in fixtures from Appendix E: include Anjali (Super Admin), Devon (Platform Admin), Kira (Support Admin), Marcus (Owner Buc-ee's), Jamie (Pricing Manager Buc-ee's), Tasha (Store Manager Buc-ee's), Hector (Night Shift Lead + Associate Buc-ee's), Anna (Owner Żabka), Piotr (Category Manager + Pricing Manager Żabka), Magda (Store Manager Żabka), Priya (Owner SmartStore), Liam (Store Manager SmartStore), Daniel (Owner FreshMart), plus 4 more to reach 17 (use plausible names matching tenant geography).
- "Locations" count: this is the count of distinct anchor org_nodes the user is assigned at. For Anjali (Super Admin, no anchor), null/em-dash. For Hector with 2 role assignments at the same node, count = 1. Easy to compute from user_role_assignments fixture data.
- Recent activity in the drawer: filter audit-logs fixture by `actor_user_id`. Most fixture users won't have audit entries; that's fine — show "No recent activity" inline.
