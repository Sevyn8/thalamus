# Prompt — Step 1.5: Shared primitives

> Paste this after Step 1.4 is committed. Last step of Phase 1.

---

## Pre-flight

```bash
pwd
git log --oneline -5             # Step 1.4 commit at top
pnpm tsc --noEmit                # zero
pnpm dev
# verify: chrome renders on every /superadmin/* route, profile menu works, persona switcher works
```

Read `BUILD_PLAN.md` Step 1.5 in full.

---

## Step ID and intent

**Step 1.5** — Empty states, loading skeletons, dialogs, drawers, toasts. The shared primitives every page in Phase 2 will reuse.

This is a CLAUDE_CODE step. After this step, a demo page exercises each primitive. Phase 2 pages then compose these without re-implementing them.

---

## Scope in

### 1. Empty state (`components/shared/EmptyState.tsx`)

```typescript
type EmptyStateProps = {
  title: string;
  body?: string;
  icon?: ReactNode;          // lucide icon
  action?: { label: string; onClick: () => void };
};
```

Centred card with icon (large, muted), title, optional body text, optional CTA button. Used when a list is empty (e.g., "No tenants yet" on Tenants page after backend returns empty).

### 2. Skeleton loader (`components/shared/Skeleton.tsx`)

One generic component that takes shape props:

```typescript
type SkeletonProps = {
  variant: "card" | "row" | "rect" | "circle" | "text";
  count?: number;            // for repeated rows
  className?: string;        // tailwind overrides for size
};
```

Use shadcn's `Skeleton` primitive as the building block; this is a higher-level wrapper that knows common shapes:

- `card`: a card-shaped placeholder (used in Tenants grid loading)
- `row`: a table-row placeholder (used in Users, Audit Log)
- `rect`: arbitrary rectangle
- `circle`: avatar placeholder
- `text`: a text line

`count` repeats the shape N times.

### 3. Confirm dialog (`components/shared/ConfirmDialog.tsx`)

Wraps shadcn `AlertDialog`. Props:

```typescript
type ConfirmDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  body: string | ReactNode;
  confirmLabel?: string;     // default "Confirm"
  cancelLabel?: string;      // default "Cancel"
  variant?: "default" | "destructive";  // destructive = red confirm button
  onConfirm: () => void | Promise<void>;
};
```

v0 does not implement type-to-confirm (that's a polish-pass feature). Just standard confirm/cancel.

### 4. Drawer (`components/shared/Drawer.tsx`)

Wraps shadcn `Sheet` (right side). Props:

```typescript
type DrawerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;        // optional sticky action row at bottom
  width?: "sm" | "md" | "lg";  // default md = 480px
};
```

Used for tenant detail, user detail, org node detail, audit event detail.

### 5. Modal (`components/shared/Modal.tsx`)

Wraps shadcn `Dialog`. Props:

```typescript
type ModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";   // default md
};
```

Used for provision tenant, invite user, add node, etc. (all of which toast "v1" on submit in v0; the modals still render).

### 6. Toast system

Use sonner (already installed). Add `<Toaster />` to `app/layout.tsx` body (or to providers).

Create `components/shared/ComingInV1Toast.tsx`:

```typescript
import { toast } from "sonner";

export function comingInV1(featureName?: string) {
  toast.info(featureName ? `${featureName} coming in v1` : "Coming in v1", {
    description: "v0 is read-only. Write actions land in v1.",
  });
}
```

This is the pre-canned toast every write CTA uses.

### 7. Status / tier / result chips

Create `components/shared/Chips.tsx` exporting:

```typescript
export function StatusChip({ status }: { status: TenantStatus | UserStatus | OrgNodeStatus }) {...}
export function TierChip({ tier }: { tier: TenantTier }) {...}
export function ResultChip({ result }: { result: AuditResult }) {...}
export function ActionChip({ action }: { action: PermissionAction }) {...}
export function ScopeChip({ scope }: { scope: PermissionScope }) {...}
```

Colour mapping per `Ithina_Admin_Frontend.md` section 7 cues:

- Status: `ACTIVE`/`SUCCESS` green; `TRIAL`/`PENDING` amber; `SUSPENDED`/`DENIED`/`TERMINATED` red; `INVITED` blue; `ARCHIVED` grey
- Tier: `ENTERPRISE` blue; `MID_MARKET` violet; `SMB` teal; `SINGLE_STORE` grey
- Action: `VIEW` grey; `CONFIGURE` blue; `EXECUTE` teal; `APPROVE` green; `OVERRIDE` red; `AUDIT` purple
- Scope: just neutral pills with the label

Each chip renders both a colour cue and a text label (per spec accessibility note: colour is never the sole carrier of meaning).

### 8. Page header (`components/shared/PageHeader.tsx`)

Every Phase 2 page has a header with title, subtitle, and optional right-aligned primary action. Reusable:

```typescript
type PageHeaderProps = {
  title: string;
  subtitle?: string;
  primaryAction?: { label: string; onClick: () => void };
};
```

When `primaryAction` is set and clicked, it calls `comingInV1(primaryAction.label)` from the v0-shell perspective. (Phase 2 pages can pass a custom `onClick`; the default behaviour is the toast.)

### 9. Demo page

Create `app/(dev)/components/page.tsx` that exercises every primitive. This is dev-only, used to verify each works in isolation. Not linked from the chrome.

Layout: a stack of sections, each demonstrating one primitive with a short caption. Toggle buttons to open/close drawer, modal, dialog. Static rendering of empty state, skeletons, every chip variant.

### 10. Loading and error boundaries

Add `app/superadmin/loading.tsx` (Next.js convention) that renders a generic skeleton during route transitions.

Add `app/superadmin/error.tsx` (Next.js convention) that renders a recovery surface with an event ID display:

```
Something went wrong.

Event ID: <request_id from caught ApiError, or generated UUID>

[Try again button]
```

For v0, this just covers uncaught render errors. Network errors are toasted at the operation level (handled by individual hooks in Phase 2).

Also add a `app/superadmin/not-found.tsx` for 404s within the console.

---

## Scope out

- Type-to-confirm dialogs (deferred polish)
- Animation polish on dialog/drawer transitions (shadcn defaults are fine)
- Real error event ID generation (use a placeholder UUID; full integration with backend `request_id` is per-page in Phase 2)
- Per-page tuned skeletons (one shared skeleton is fine for v0)
- A 403 surface (deferred; v0 backend has no permission errors yet)

---

## Acceptance criteria

1. All 7 shared components exist under `components/shared/`
2. Toast system works: calling `comingInV1()` shows a toast
3. Demo page at `/dev/components` renders every primitive without errors
4. `app/superadmin/loading.tsx` renders during route transitions
5. `app/superadmin/error.tsx` catches a thrown error (manually test by adding a thrown error in a placeholder, verifying the boundary catches it, then removing)
6. Chips render with correct colours for each variant
7. `pnpm tsc --noEmit` exits zero
8. No console errors
9. `BUILD_PLAN.md` Step 1.5 flipped to DONE

---

## After completing the step

1. Confirm acceptance
2. Report:
   - Files added
   - Any primitives you found you needed but the prompt didn't mention (and added)
   - Any prompts where you chose a shadcn primitive different from what the prompt suggested
3. Update BUILD_PLAN.md (mark Step 1.5 DONE; Phase 1 complete)
4. Propose commit:
   ```
   git add -A
   git commit -m "Step 1.5: shared primitives (empty states, skeletons, dialogs, chips, toasts)"
   ```
5. Wait for user direction before Step 2.1 (Phase 2 begins)

---

## Note on Phase 2

Phase 2 builds 8 pages, one per step. Each page composes the primitives from this step plus the data hooks from Step 1.3. The pages should feel formulaic to build because the foundation is in place. If you find a page needs a primitive that doesn't exist, add it to `components/shared/` rather than inlining it in the page.
