# Prompt — Step 3.2: Profile, notifications, approvals (shells)

> Paste this after Step 2.8 is committed. Final step of v0.

---

## Pre-flight

```bash
pwd
git log --oneline -10            # Step 2.8 at top, Phase 2 complete
pnpm tsc --noEmit                # zero
pnpm dev
# verify: all 8 main pages render and work end-to-end
```

Read `BUILD_PLAN.md` Step 3.2 and `Ithina_Admin_Frontend.md` sections 8.2 (Notifications), 11.5 (Profile), 11.6 (Approval inbox).

---

## Step ID and intent

**Step 3.2** — Implied surfaces as shells. Profile (read-only), Notifications (full inbox), Approvals (placeholder).

This is a CLAUDE_CODE step. Step 3.1 (Auth screens) is deferred until Auth0 lands; only this step runs in v0.

---

## Scope in

### 1. /profile

Path: `app/profile/page.tsx`. NOT under `/superadmin` (per spec it's outside the superadmin scope).

This was scaffolded as a placeholder in Step 1.4. Now flesh it out:

```
+----------------------------------------+
| Profile                                |
+----------------------------------------+
| ACCOUNT                                |
|   Avatar (large, initials)             |
|   Anjali Mehta                         |
|   anjali@ithina.ai                     |
|   Super Admin                          |
|   Platform (Ithina)                    |
+----------------------------------------+
| SECURITY                               |
|   Password: ••••••••     [Change*]     |
|   MFA: Enabled (TOTP)    [Manage*]     |
+----------------------------------------+
| NOTIFICATION PREFERENCES               |
|   In-app notifications: On             |
|   Email notifications:  On             |
|   (toggles, all toast "v1")            |
+----------------------------------------+
```

* All buttons toast "v1" or "Will land with Auth0 integration".

Read current user from JWT via `getCurrentUser()`. Server component is fine.

The chrome already wraps this page (the layout in `app/superadmin/layout.tsx` doesn't apply here because /profile is outside /superadmin). Decide: does /profile use the same chrome or no chrome?

Spec implies same chrome. Solution: extract the chrome layout into a shared layout group. Use Next.js route groups: `app/(authenticated)/superadmin/...` and `app/(authenticated)/profile/...` both share `app/(authenticated)/layout.tsx` which contains the chrome.

You'll need to refactor the existing `/superadmin/layout.tsx` into the new route group structure. Be careful: the middleware redirect targets need to stay correct (`/superadmin/*` paths should still match).

### 2. /notifications

Path: `app/(authenticated)/notifications/page.tsx`.

Full inbox. Spec section 8.2.

```
+----------------------------------------+
| Notifications                  [Filter]|
+----------------------------------------+
| Tabs: [All] [Unread]                   |
+----------------------------------------+
| List of notifications                  |
| [unread dot] Title                     |
| Body                                   |
| 2 min ago               [Open]         |
| ───────────────────────                |
| ...                                    |
+----------------------------------------+
```

For v0:
- `useNotifications()` returns ~10 mock notifications from fixture
- Each notification: `{id, title, body, occurred_at, read, deep_link}`
- Tabs filter by read state; URL `?filter=all|unread`
- "Open" button on each item: navigates to `deep_link`
- "Mark all as read" button at top: toasts "v1"

Add `mocks/fixtures/notifications.json` and matching API/handler/hook if they don't exist. Notifications wasn't in Step 1.3's resource list; add it now.

### 3. /approvals

Path: `app/(authenticated)/approvals/page.tsx`.

Spec section 11.6 says this is an open question (where do approvers see pending approvals). For v0, ship a placeholder:

```
+----------------------------------------+
| Approvals Inbox                        |
+----------------------------------------+
|                                        |
| [Empty state]                          |
| "Approvals inbox coming in v1."        |
| "Pending approvals will appear here    |
|  when guardrails fire."                |
|                                        |
+----------------------------------------+
```

Just an empty state. Don't build the inbox; it's deferred.

### 4. Notifications popover update

Top bar's notifications bell (built in Step 1.4) currently shows mock items. Verify those items are sourced from the same `useNotifications()` hook (use limit=10, sorted by occurred_at desc). Add a "View all" link at the bottom of the popover linking to `/notifications`.

### 5. Auth screens placeholder (Step 3.1 deferred, but minimal touch)

Per BUILD_PLAN Step 3.1 is DEFERRED. But the route shells should exist so middleware doesn't redirect to broken URLs. Create minimal placeholders if not already present:

- `app/login/page.tsx` — "Login is handled by Auth0 in production. In dev, use /dev/login for persona switching." (Or, in stub mode, just redirect to /dev/login.)
- `app/forgot-password/page.tsx` — "Password reset is handled by Auth0 in production."
- `app/accept-invite/[token]/page.tsx` — "Invite acceptance is handled by Auth0 in production."
- `app/mfa/setup/page.tsx` — "MFA setup is handled by Auth0 in production."
- `app/mfa/challenge/page.tsx` — "MFA challenge is handled by Auth0 in production."

These are all unauthenticated routes. Don't apply the chrome layout to them.

---

## Scope out

- Real Auth0 screens (deferred to Auth0 landing)
- Real notification triggers (notifications appear because fixture data, not because something happened)
- Real approval inbox (deferred)
- Notification preferences write (toggles toast "v1")
- Profile editing (toasts)
- MFA management UI (deferred to Auth0)

---

## Acceptance criteria

1. Route group refactor: `app/(authenticated)/layout.tsx` wraps both `/superadmin/*` and `/profile`, `/notifications`, `/approvals` with chrome
2. `/superadmin/*` still works exactly as before the refactor
3. `/profile` renders current user's read-only details with chrome
4. `/notifications` renders inbox with ~10 mock items, tabs, mark-all-as-read button
5. `/approvals` renders empty state placeholder
6. Notification popover in top bar uses same data source as `/notifications`; "View all" link works
7. Auth-related placeholder pages render without errors and don't break middleware
8. Logout still clears cookie and redirects correctly
9. `pnpm tsc --noEmit` exits zero
10. No console errors
11. BUILD_PLAN.md Step 3.2 flipped to DONE; v0 SHELL COMPLETE

---

## After completing the step

1. Confirm acceptance — and confirm v0 shell complete
2. Report:
   - Files added/modified
   - Route-group refactor details (because middleware/layout changes are subtle)
   - The "v0 shell complete" milestone
3. Update BUILD_PLAN.md final summary
4. Propose commit:
   ```
   git add -A
   git commit -m "Step 3.2: profile, notifications, approvals shells; v0 complete"
   ```
5. Stop. Wait for user direction. Phase 4 (wiring) is interactive against backend deliverables, not a single step.

---

## v0 done state

When this step lands and is committed:

- All 8 main pages render with mocked data
- Chrome present on every authenticated route
- Persona switcher works
- Drawers, modals, dialogs, toasts all working
- Empty and loading states defined
- Page-level CTAs toast "v1" on click
- Row-level kebabs hidden
- TypeScript strict passes
- No console errors

The frontend is ready to demo end-to-end against mocks. Wiring (Phase 4) starts as Sanjeev's backend endpoints land. Each wiring task is small: flip one entry in `mocks/config.ts` from `"mock"` to `"real"`, verify the page still renders the same thing.

---

## If you hit a snag

- Route group refactor breaks chrome on /superadmin: this is the trickiest part of the step. Test each /superadmin/* page after the refactor. The middleware regex shouldn't need changes (it matches paths, not layouts).
- /profile under chrome but the chrome's "Profile" link in the user menu used to navigate via Next router: confirm that still works after refactor.
- Notifications fixture: produce 10 entries covering the trigger types in spec section 8.2 (guardrail fired, approval escalated, MFA reset, invite, tenant suspended). Mix read and unread.
