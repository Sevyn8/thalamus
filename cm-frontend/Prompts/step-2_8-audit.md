# Prompt — Step 2.8: Audit Log

> Paste this after Step 2.7 is committed. Last page in Phase 2.

---

## Pre-flight

```bash
pwd
git log --oneline -5
pnpm tsc --noEmit                # zero
pnpm dev
```

Read `BUILD_PLAN.md` Step 2.8, `Ithina_Admin_Frontend.md` section 7.8 (Audit Log), `tenants-api-contract-v0.md` Part 4.

---

## Step ID and intent

**Step 2.8** — The Audit Log page. Wide table, search, 4 filter tabs, detail drawer.

This is a CLAUDE_CODE step.

---

## Scope in

### 1. Page layout

Path: `app/superadmin/audit/page.tsx`.

```
+----------------------------------------------------------------+
| PageHeader                                                     |
|   title: "Audit Log"                                           |
|   subtitle: "Immutable record of every user, role, permission, |
|              module, and override action."                     |
|   right side: [Reset demo data]* [Export CSV]                   |
+----------------------------------------------------------------+
| Search input                                                   |
| Filter tabs: [All] [Success] [Denied] [Pending]                |
+----------------------------------------------------------------+
| Wide table                                                     |
| | TIME | ACTOR | TENANT | ACTION | RESOURCE | SCOPE | RESULT | IP |
+----------------------------------------------------------------+
```

* "Reset demo data" only renders when `NEXT_PUBLIC_DEMO_MODE=true`; click toasts "v1".

"Export CSV" toasts "v1".

### 2. Search and filter

Search: debounced 300ms. Filters by actor name, action label, resource, tenant. URL `?search=...`.

Filter tabs: shadcn `Tabs`. Values `ALL` (default), `SUCCESS`, `DENIED`, `PENDING`. URL `?result=...`.

### 3. Table

Component: `components/audit/AuditTable.tsx`.

Columns:

| Column | Notes |
|---|---|
| TIMESTAMP | Monospace, format `YYYY-MM-DD HH:MM:SS` |
| ACTOR | Avatar + name (bold) + role label below in muted; "System" with no avatar for system actor |
| TENANT | Tenant name or "Platform" for null tenant_id |
| ACTION | Action label as plain text |
| RESOURCE | Free-form display string |
| SCOPE | scope chip (Global/Tenant/Region/Store) or em-dash |
| RESULT | result chip (success/denied/pending) |
| IP | IPv4/IPv6 in monospace, em-dash for system |

Row click: opens detail drawer.

Pagination: Use `?offset=...&limit=...`. Default limit 50. Show "Showing 1-50 of N" + Prev/Next at bottom.

### 4. Audit event detail drawer

Component: `components/audit/AuditDetailDrawer.tsx`.

```
+----------------------------------------+
| [Action label]                    [×]  |
| 2026-04-19 14:42:11   [Result chip]    |
+----------------------------------------+
| ACTOR                                  |
|   [Avatar] Anjali Mehta                |
|   anjali@ithina.ai                     |
|   Super Admin                          |
|   IP: 10.0.4.22                        |
+----------------------------------------+
| TENANT                                 |
|   Buc-ee's →                           |
+----------------------------------------+
| RESOURCE                               |
|   Promotions Assistant → Buc-ee's      |
|   Scope: Tenant                        |
+----------------------------------------+
| PAYLOAD                                |
|   { "module": "PROMOTIONS_ASSISTANT",  |
|     "tenant_id": "..." }               |
+----------------------------------------+
| RELATED EVENTS                         |
|   (links to parent / children)         |
+----------------------------------------+
```

Tenant in the drawer is a clickable link to `/superadmin/tenants?tenant=<id>` (opens that tenant's drawer on the Tenants page).

Payload: render as JSON with monospace font in a scrollable `<pre>` block. Pull from fixture; can be a small example payload.

Related events: skip in v0 (deferred).

### 5. URL state

`?event=<id>` opens drawer. Reload restores.

### 6. Empty state

"No audit events match your filter."

### 7. Loading

Table: 10 row skeletons. Drawer: skeleton blocks.

---

## Scope out

- Real CSV export (button toasts "v1")
- Date range filter (open question per spec; defer)
- Tenant / module / actor filter dropdowns beyond the 4 result tabs (defer)
- Reset demo data confirmation dialog (button toasts "v1")
- Related events drill-down
- Real-time updates / streaming
- Before/after diff payload

---

## Acceptance criteria

1. `/superadmin/audit` renders the audit table with ~20 fixture events
2. Subtitle and column headers correct
3. "Export CSV" toasts "v1"
4. "Reset demo data" only visible when `NEXT_PUBLIC_DEMO_MODE=true`; toasts "v1" when clicked
5. Search filters across actor/action/resource/tenant; URL updates
6. Filter tabs filter by result; URL updates
7. Pagination Prev/Next works at bottom of table
8. Row click opens detail drawer with structured payload
9. Tenant link in drawer navigates to Tenants page with that tenant drawer open
10. URL state for filters and event drawer survives reload
11. `pnpm tsc --noEmit` exits zero
12. No console errors
13. BUILD_PLAN.md Step 2.8 flipped to DONE; Phase 2 complete

---

## After completing the step

1. Confirm
2. Report any fixture extensions (especially the 20 audit events covering the action labels in spec Section 10)
3. Note that Phase 2 is complete after this commit
4. Update BUILD_PLAN.md
5. Propose commit:
   ```
   git add -A
   git commit -m "Step 2.8: Audit Log page with table, filters, detail drawer"
   ```
6. Wait before Step 3.2

---

## If you hit a snag

- 20 audit events spread across action types: include at least one of each — Created tenant, Tenant suspended (System actor variant), Org node created, Invited user, Created custom role, Permission grant, Enabled module, Configured guardrail, Approved action, Denied action (override denied), Override attempt, Bulk donation routed, Impersonation start. Cover the variety so the page exercises every chip variant.
- Monospace font for timestamp/IP: Tailwind `font-mono` is fine.
- JSON payload syntax highlighting: not required for v0. Just `<pre>` with `whitespace-pre`.
- System actor display: no avatar (or a special icon like a cog), name "System", no role label, IP em-dash.
