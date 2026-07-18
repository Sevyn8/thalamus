# Prompt — Step 2.7: Guardrails

> Paste this after Step 2.6 is committed.

---

## Pre-flight

```bash
pwd
git log --oneline -5
pnpm tsc --noEmit                # zero
pnpm dev
```

Read `BUILD_PLAN.md` Step 2.7 and `Ithina_Admin_Frontend.md` section 7.7 (Guardrails and Approvals).

**Important context.** Backend has no guardrails or approvals tables yet. This page is mock-only in v0, contributing display only. Wiring waits for those tables to ship in a later backend phase.

---

## Step ID and intent

**Step 2.7** — The Guardrails page. List of 5 fixture guardrails with stat cards top.

This is a CLAUDE_CODE step.

---

## Scope in

### 1. Page layout

Path: `app/superadmin/guardrails/page.tsx`.

```
+----------------------------------------------------------------+
| PageHeader                                                     |
|   title: "Guardrails & Approvals"                              |
|   subtitle: "Define approver workflows, escalation timers,     |
|              and override authority for high-impact actions."  |
|   primaryAction: "+ New guardrail"  → toasts "v1"              |
+----------------------------------------------------------------+
| 3 stat cards: [Active rules] [Avg escalation] [Triggered 24h]  |
+----------------------------------------------------------------+
| List of guardrail rows                                         |
+----------------------------------------------------------------+
```

### 2. Stat cards

Component: `components/guardrails/GuardrailStatCard.tsx` (or reuse `KpiCard` from Step 2.1 in a slimmer variant).

Three stats from fixture:
- Active rules: count of guardrails with status=ACTIVE
- Avg escalation: average of escalate_after_hours across active rules ("8h")
- Triggered (24h): mock number from fixture (e.g. "23")

These can be derived in the component from `useGuardrails()` data.

### 3. Guardrail row

Component: `components/guardrails/GuardrailRow.tsx`.

Each row of the list shows one guardrail:

```
+--------------------------------------------------+
| [Icon]  Markdown > 30%                  [toggle] |
| [Pricing OS]  [active]                  [kebab]  |
|                                                  |
| Trigger: Markdown depth exceeds 30%              |
|                                                  |
| APPROVERS         ESCALATE AFTER  OVERRIDE       |
| [Pricing Manager] 4h              [Owner]        |
| [Owner]                                          |
+--------------------------------------------------+
```

Layout: card-shaped, rounded border, padding. Status pill colour: ACTIVE green, DRAFT grey, PAUSED amber.

Module pill: matches the action chip styling but in a different colour (use neutral-blue tint).

Approvers: row of role chips (one per approver role).

Escalate After: clock icon + duration.

Override Authority: single role chip.

Right side: a `Switch` toggle. Reflects current `status === ACTIVE`. Click: toasts "v1" (and visually flips momentarily then reverts, same pattern as Step 2.6).

Kebab menu (hidden in v0).

### 4. Five fixture guardrails

From spec section 7.7.3:

1. Markdown > 30% (Pricing OS, "Markdown depth exceeds 30%", Pricing Manager + Owner, 4h, Owner)
2. Bulk Donation Routing (Perishables Assistant, "Donation batch > 200 units", Store Manager, 12h, Owner)
3. Promo Activation Tenant-Wide (Promotions Assistant, "Campaign scope = entire tenant", Marketing + Owner, 24h, Owner)
4. Role Assignment > Manager (Admin, "Assigning Owner / Pricing Mgr", Owner, 8h, Platform Admin)
5. Module Enable / Disable (Admin, "Toggling tenant module", Platform Admin, 4h, Super Admin)

Confirm `mocks/fixtures/guardrails.json` has these 5. If not, add them.

### 5. Empty state

If filtered to zero (no filter UI in v0, but for safety): "No guardrails configured. Create your first guardrail to gate high-impact actions."

### 6. Loading

3 stat card skeletons + 5 row skeletons.

---

## Scope out

- New guardrail modal (toast "v1")
- Edit guardrail modal
- Delete confirmation
- Guardrail detail page (kebab "View fires")
- Approval inbox (open question per spec section 11.6)
- Approval detail with payload + Approve/Deny buttons
- Runtime fire / approve / deny / escalate / override flows
- Filter by module, by status

---

## Acceptance criteria

1. `/superadmin/guardrails` renders with 3 stat cards and 5 guardrail rows
2. Stat cards show correct derived numbers
3. Each row shows: name, module pill, status pill, trigger condition, approver chips, escalate-after, override authority, status toggle
4. Click toggle: toasts "v1" with optimistic visual flip
5. "+ New guardrail" toasts "v1"
6. `pnpm tsc --noEmit` exits zero
7. No console errors
8. BUILD_PLAN.md Step 2.7 flipped to DONE

---

## After completing the step

1. Confirm
2. Report fixture additions
3. Update BUILD_PLAN.md
4. Propose commit:
   ```
   git add -A
   git commit -m "Step 2.7: Guardrails page with stat cards and rule list"
   ```
5. Wait before Step 2.8

---

## If you hit a snag

- Module pill colour scheme: pick a different colour family from action chips so they don't visually conflict. Module pills are informational; action chips are categorical.
- Triggered (24h) stat: fixture-driven value, not derived from a fires-table (which doesn't exist). Just put a static number like 23 in the stat card or hardcoded in the fixture.
- Multiple approvers display: render as a wrapped row of role chips with comma or space separation.
