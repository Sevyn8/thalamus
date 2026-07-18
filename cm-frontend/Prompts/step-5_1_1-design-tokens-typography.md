# Step 5.1.1 — Design Tokens + Typography System

## Context and intent

v0 shell + Phase 4a anchor write are complete. The build works, but the user has reviewed the running app and reported it doesn't feel enterprise-grade — typography feels generic, spacing is inconsistent, the surface reads like an ad-hoc shadcn shell rather than a deliberate enterprise admin tool.

Tier 1 polish targets this gap. The aesthetic anchor is **Salesforce-adjacent enterprise B2B admin**: dense, table-heavy, utilitarian, built with modern primitives (think NetSuite, Workday, ServiceNow rebuilt in 2024). Light by default, dark as a toggle.

This step is the foundation. Tokens come first because everything else (light mode in 5.1.2, animations in 5.1.3, polish in 5.1.4) references them. Without canonical tokens, polish gets layered onto an inconsistent foundation and never quite resolves.

**Out of scope for this step:**
- Light mode (5.1.2)
- Animations and micro-interactions (5.1.3)
- +N overflow, type-to-confirm, card/table polish (5.1.4)

In other words: the app should look the same after this step in terms of behavior and visual feel — what changes is that ad-hoc Tailwind classes get replaced with token references, and inconsistencies get canonicalized in passing. No animation, no light mode, no new layouts.

## Aesthetic anchor: Salesforce-adjacent enterprise B2B admin

Concrete reference points (look at these for calibration, don't reproduce them):

- **Body text size:** 14px / 13px secondary. Not 16px. Density matters; Salesforce Lightning is 13-14px throughout.
- **Type scale:** modest jumps. Page title is `text-xl` (20px) or `text-2xl` (24px), not `text-3xl` or `text-4xl`. Section headers are `text-base` semibold. Most labels are `text-xs` uppercase tracking-wide.
- **Spacing:** dense. Card padding is 16px (`p-4`), not 24px. Row heights are 40-48px, not 56px. Gaps between major sections are 24px (`gap-6`), not 48px.
- **Colors:** muted, work-focused. Background is near-white off-grey (`#FAFAFA`-ish), surfaces are pure white, borders are visible but soft (`#E5E7EB`-ish). Primary action color is a single confident accent (Salesforce uses blue; we'll use a slightly modernized blue). Status colors are saturated but not loud.
- **Borders:** present and consistent. Cards have `border` not `shadow`. Tables have row dividers. Inputs have `border` not floating elevation.
- **Shadows:** sparing. Modals and dropdowns get subtle shadows; cards do not. Elevation tells a story; if everything elevates, nothing elevates.

This is the calibration target. Don't slavishly mimic Salesforce — they have 20 years of legacy. Build a clean version of the same vibe.

## Acceptance criteria

1. `app/globals.css` (or wherever Tailwind directives live) defines the canonical token set as CSS custom properties under `:root` for the dark theme (current default; light variant added in 5.1.2). Tokens cover: typography scale, spacing scale, color palette (foreground, background, surface, border, primary, secondary, muted, accent, semantic — success/warning/danger/info), border radius, shadow elevation tiers.
2. `tailwind.config.ts` (or v4 inline config in CSS) is updated to expose these tokens as Tailwind utility values. Where shadcn defaults already use CSS vars (e.g., `--background`, `--foreground`, `--primary`), refine those values rather than introducing parallel tokens.
3. A new `lib/design-tokens.ts` (or `theme.ts`) exports the token names as TypeScript constants for any non-Tailwind consumer (e.g., chart colors, manual style props). Single source of truth.
4. **Typography pass across all 8 pages.** Replace ad-hoc text size classes (`text-3xl`, `text-2xl`, `text-lg`, `text-xs` used inconsistently) with a canonical scale. Document the scale at the top of `app/globals.css` as a comment.
5. **Spacing pass across all 8 pages.** Replace ad-hoc padding/margin/gap (e.g., `p-3` here, `p-4` there, `p-6` somewhere else for similar containers) with token-driven values. Card padding canonical, row spacing canonical, page-level container padding canonical.
6. **Color pass.** Replace direct color references (`text-zinc-400`, `bg-slate-900`, `border-gray-700`, etc.) with semantic token references (`text-muted-foreground`, `bg-surface`, `border-border`). Where shadcn already does this via its CSS var system, leave it alone; only fix the ad-hoc ones.
7. **Border-radius pass.** Standardize on a small set: `rounded-sm` (2px) for inline elements, `rounded` (4px) for inputs/buttons, `rounded-md` (6px) for cards/modals. No `rounded-lg` or `rounded-2xl` unless it's a deliberate visual emphasis.
8. The 8 pages still render with the same content and behavior. No new components, no removed components, no layout restructures.
9. Pre-existing functionality preserved: persona switcher, provision tenant flow, drawer open/close, search, filters, audit log filtering, etc. Smoke-verify each page still loads.
10. `pnpm tsc --noEmit` exits zero.
11. `pnpm lint` exits zero.
12. `pnpm build` succeeds.
13. No console errors during page navigation (modulo the pre-existing activation race on cold load).
14. BUILD_PLAN.md updated: Step 5.1.1 → DONE; Phase 5a entry shows 5.1.1 done, 5.1.2/5.1.3/5.1.4 remaining.
15. PATTERNS.md updated with a "Design tokens" section explaining the scale and how to use it (one paragraph + the canonical scale table).

## Token specification

This is the canonical scale. Implement these. If a value below conflicts with shadcn's default CSS var name, refine the shadcn variable's value rather than adding a parallel one.

### Typography scale

| Token | Size | Line height | Weight | Use |
|---|---|---|---|---|
| `text-display` | 24px | 32px | 600 | Page titles (one per page) |
| `text-heading` | 18px | 24px | 600 | Section headers within a page |
| `text-subheading` | 15px | 22px | 600 | Card titles, drawer titles |
| `text-body` | 14px | 20px | 400 | Default body text |
| `text-body-strong` | 14px | 20px | 500 | Emphasized inline body |
| `text-secondary` | 13px | 18px | 400 | Captions, table cells secondary, helper text |
| `text-label` | 12px | 16px | 500 uppercase tracking-wide | Form labels, table column headers, eyebrow text |
| `text-micro` | 11px | 14px | 400 | Timestamps, tertiary metadata |

Font family: stick with what v0 has (Inter, presumably, via Next.js font integration). Don't introduce a new font.

### Spacing scale

Canonicalize to the 4px grid Tailwind already uses. Define semantic aliases for common cases:

| Token | Value | Use |
|---|---|---|
| `space-page` | 24px (`p-6`) | Outermost page container padding |
| `space-section` | 24px (`gap-6`) | Between major page sections |
| `space-card` | 16px (`p-4`) | Card internal padding |
| `space-card-gap` | 12px (`gap-3`) | Gap between elements within a card |
| `space-row` | 12px (`py-3`) | Table row vertical padding (compact density) |
| `space-form-field` | 16px (`gap-4`) | Between form fields in a stack |
| `space-inline` | 8px (`gap-2`) | Between adjacent inline elements (icon + label, etc.) |

The Tailwind classes work as-is; what changes is documenting which class to use where, so the next developer (or you in two weeks) doesn't ad-hoc.

### Color palette (dark theme — light comes in 5.1.2)

Use the shadcn CSS var slot names where they exist; refine the values:

| Token | Dark value (refine current) | Use |
|---|---|---|
| `--background` | `#0A0B0D` (deeper than current zinc) | Page background |
| `--surface` | `#15171A` (new) | Cards, drawer, modal background |
| `--surface-raised` | `#1C1F23` (new) | Hover state, popovers |
| `--foreground` | `#E5E7EB` | Primary text |
| `--foreground-muted` | `#9BA1A6` | Secondary text |
| `--foreground-subtle` | `#6B7280` | Tertiary, placeholders |
| `--border` | `#26282D` (refine current) | Default borders |
| `--border-strong` | `#3A3D42` (new) | Emphasized borders, focus rings |
| `--primary` | `#3B82F6` (modernized blue) | Primary CTAs, links, focused states |
| `--primary-foreground` | `#FFFFFF` | Text on primary |
| `--success` | `#10B981` | Active status, success toast |
| `--warning` | `#F59E0B` | Trial status, pending |
| `--danger` | `#EF4444` | Suspended, destructive actions, error toast |
| `--info` | `#6366F1` | Informational, neutral status |

Tier badge colors (existing v0 chips): keep current vocabulary (Enterprise blue, Mid-Market violet, SMB teal, Single-Store grey) but pull from this token set rather than hex. Same for status chips.

### Border radius

| Token | Value | Use |
|---|---|---|
| `--radius-sm` | 2px | Inline pills, badges, small chips |
| `--radius` | 4px | Buttons, inputs, dropdowns |
| `--radius-md` | 6px | Cards, modals, drawers |

No values above 6px. Salesforce-adjacent doesn't use big rounded corners.

### Shadow elevation

| Token | Value | Use |
|---|---|---|
| `--shadow-none` | `none` | Cards (use border instead) |
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.3)` | Dropdowns, menus |
| `--shadow-md` | `0 4px 12px rgba(0,0,0,0.4)` | Modals, drawers |

Three tiers max. No `shadow-xl`, no glows, no double-shadows.

## What "the typography pass" actually looks like

Concretely, here's what changes per page. Don't restructure; just replace classes.

### Dashboard (`app/(authenticated)/superadmin/dashboard/page.tsx`)

- Page title "Superadmin Dashboard": currently probably `text-3xl font-bold` → becomes `text-display` (24px).
- Subtitle: any size variant → `text-secondary text-foreground-muted`.
- KPI metric numbers: large display → keep large but use a consistent size, maybe `text-2xl font-semibold`. Specify and use throughout.
- KPI labels: `text-label text-foreground-muted` (12px uppercase).
- KPI subtext: `text-secondary text-foreground-muted`.
- "Top tenants by users" panel header: `text-subheading`.
- "Manage all →" link: `text-secondary text-primary`.
- Tenant row name: `text-body-strong`.
- Tenant row "industry · country": `text-secondary text-foreground-muted`.
- Tenant row counts (right side): `text-body`.
- Recent activity actor name: `text-body-strong`.
- Recent activity action: `text-secondary`.
- Recent activity timestamp: `text-micro text-foreground-subtle`.

### Tenants (`app/(authenticated)/superadmin/tenants/page.tsx` and `components/tenants/*`)

- Page title "Tenants": `text-display`.
- Subtitle "{n} client organizations · {m} stores": `text-secondary text-foreground-muted`.
- "+ Provision tenant" button: standard button sizing — let shadcn handle.
- Search input: standard input.
- Filter tabs: tab text `text-body`, active tab unchanged.
- Tenant card name: `text-subheading`.
- Tenant card "industry · country": `text-secondary text-foreground-muted`.
- Tier/status chips: unchanged (already using chip tokens).
- Stat box label ("Stores", "Users", "MRR"): `text-label text-foreground-muted`.
- Stat box value: `text-heading` (18px semibold).
- Module pill: `text-micro`.

### TenantDetailDrawer

- Drawer title (tenant name): `text-subheading`.
- Drawer subtitle (industry · country · onboarded): `text-secondary text-foreground-muted`.
- "PRIMARY CONTACT" / "MODULES ENABLED" / "LIVE COUNTS" eyebrows: `text-label text-foreground-muted`.
- Block content: `text-body`.

### ProvisionTenantModal

- Modal title "Provision new tenant": `text-subheading` (already done by Modal primitive — verify).
- Modal subtitle: `text-secondary text-foreground-muted`.
- Field labels: `text-label text-foreground-muted`.
- Field help text: `text-secondary text-foreground-subtle`.
- Field error messages: `text-secondary text-danger`.

### Other pages (Users, Org Tree, Roles & Permissions, Module Access, Guardrails, Audit Log)

Apply the same pattern. Page title `text-display`, subtitle `text-secondary text-foreground-muted`, table column headers `text-label text-foreground-muted`, table cells `text-body`. Use judgment — the principle is: **every text element should match one of the 8 typography tokens**. If a text element doesn't match any, default to `text-body`.

## What "the spacing pass" actually looks like

Less prescriptive than typography because spacing depends on visual context. Heuristics:

- **Card internal padding:** `p-4` (16px) for tenant cards, KPI cards, dashboard panels. Replace any `p-3`, `p-5`, `p-6` for cards with `p-4`.
- **Page-level container:** wrap each page's main element in `p-6` (24px). Replace any inconsistent page padding.
- **Between sections of a page:** `space-y-6` or `gap-6`. Replace any `space-y-4`, `space-y-8`.
- **Form field stacks:** `gap-4` (16px) between fields. The Provision modal's form already uses this; verify and align.
- **Drawer/modal content padding:** `p-6` for the body, header/footer padding driven by shadcn defaults — leave alone.

After: spacing reads as deliberate, not ad-hoc.

## What "the color pass" actually looks like

This one is mechanical. Find every direct color class and replace with a semantic token reference:

- `text-zinc-400` / `text-gray-400` / `text-slate-400` → `text-foreground-muted`
- `text-zinc-500` / `text-gray-500` → `text-foreground-subtle`
- `text-zinc-100` / `text-gray-100` / `text-white` (on page backgrounds) → `text-foreground`
- `bg-zinc-900` / `bg-slate-900` (page bg) → `bg-background`
- `bg-zinc-800` / `bg-slate-800` (card bg) → `bg-surface`
- `border-zinc-800` / `border-gray-800` → `border-border`
- Status-meaningful colors (red for danger, green for success, etc.): keep semantic, refine to use the new color tokens.

shadcn components that already use `text-foreground`, `bg-background`, `border-input`, etc., are already correct — leave them alone.

Use `grep -rn 'zinc\|slate\|gray-' app/ components/ lib/` to find ad-hoc references. Replace systematically.

## Implementation approach

1. **Define tokens first.** Write the CSS vars in `app/globals.css`. Update `tailwind.config.ts` to expose them as utilities. Verify the demo page (`/dev/components`) still renders correctly — this is the smoke test before you touch the 8 pages.
2. **Token sweep page by page.** Dashboard first (most visible), then Tenants (most polished v0 page), then the others. Commit incrementally if the diff gets large; otherwise one commit at the end is fine.
3. **Don't restructure.** If you find yourself wanting to refactor a component because it'd be cleaner — stop. Note it for 5.1.4 (final pixel pass) and move on. This step is purely tokens.
4. **Visual smoke after each page.** Open the page in the browser. Compare to the previous look. The page should look more deliberate, not different. If it looks different (layout shifted, content moved), back out the change.

## Files modified

Likely:
- `app/globals.css` (token definitions, scale documentation)
- `tailwind.config.ts` (utility exposure)
- `lib/design-tokens.ts` (new — TypeScript constants)
- `app/(authenticated)/superadmin/*/page.tsx` × 8 pages (typography + spacing + color sweep)
- `components/dashboard/*.tsx` (typography sweep on KpiCard, TopTenantsPanel, RecentActivityPanel)
- `components/tenants/*.tsx` (typography sweep on TenantCard, TenantDetailDrawer, ProvisionTenantModal)
- `components/users/*.tsx`, `components/org/*.tsx`, etc. (sweep across all 8 pages' components)
- `components/shared/Chips.tsx` (refine to use new color tokens)
- `BUILD_PLAN.md` (Step 5.1.1 → DONE)
- `PATTERNS.md` (add "Design tokens" section)

Estimated diff size: 80-150 files touched, mostly small (1-3 line changes per file replacing class names). Don't be surprised if the diff is wide but shallow.

## Smoke checklist

After all changes:

1. Persona switcher → log in as Anjali. Dashboard renders. Compare to memory of pre-step look — should feel more deliberate, denser, more "real product."
2. Tenants page. 7 cards render. Stat boxes look consistent. Module pills render. Card padding looks even.
3. Click a tenant card. Drawer opens with correct typography.
4. Click "+ Provision tenant". Modal opens. Field labels are uppercase tracking-wide. Field spacing consistent.
5. Submit a tenant. Optimistic insert works (4.1 functionality preserved).
6. Switch to Marcus persona. Sidebar items unchanged.
7. Walk through Users, Org Tree, Roles & Permissions, Module Access, Guardrails, Audit Log. Each page's title is `text-display`. Each page's table headers are `text-label`. Spacing feels consistent across pages.
8. `/dev/components` demo page still renders all primitives.
9. No console errors (modulo pre-existing activation race).
10. `pnpm build` succeeds.

## Process notes

- Pre-mark "no console errors" as ⚠️ (activation race continues).
- Pre-smoke self-check before browser smoke. Verify token definitions are coherent (no orphan tokens, no token names unused, no values that contradict the table above) before sweeping the pages.
- This step touches a lot of files. Be disciplined: tokens first, sweep second. Don't sweep before tokens are in place.
- If you find a place where the typography scale doesn't quite fit (e.g., a number that genuinely needs to be larger than `text-display`), pause and ask. Don't invent a 9th typography token mid-sweep.
- If you find shadcn primitive defaults that conflict with our tokens (e.g., shadcn's `Card` has `p-6` baked in and we want `p-4`), override in the shadcn component file rather than overriding everywhere it's used. Single point of change.

## Ask before building

Things worth surfacing upfront:

- Whether v0 has a preferred font setup (Inter via Next.js font, or another). Confirm before assuming.
- Whether shadcn primitives in this codebase are eject-style (their source is in `components/ui/`) or import-style (from `node_modules`). If eject-style, we can edit them directly; if import-style, we override via Tailwind classes at consumption sites.
- Whether `tailwind.config.ts` exists in the v0 codebase or if it's a Tailwind v4 inline-config setup. The approach to extending the theme differs.
- If any of the token color values above feel wrong against the existing v0 dark palette, surface for adjustment before doing the sweep. Better to nudge values now than re-sweep later.

Post the pre-smoke self-check structured table when ready, same shape as v0 steps. After smoke passes, propose the commit. Expected commit message:

> Step 5.1.1: Design tokens + typography system
>
> Foundation for Tier 1 polish. Canonical typography scale (8 tokens), spacing scale, color palette (dark theme refined; light comes in 5.1.2), border-radius scale, shadow elevation tiers. CSS vars + Tailwind utilities + TypeScript constants. Sweep across all 8 pages replaces ad-hoc classes with token references.
>
> Behavior unchanged. Visual feel more deliberate; less ad-hoc. Sets up 5.1.2 (light mode), 5.1.3 (animations), 5.1.4 (final polish).
