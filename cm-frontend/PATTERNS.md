# Project patterns

Captured patterns and gotchas discovered during the build. Read before writing similar code.

## Form patterns (captured post Step 4.1)

- Numeric inputs: use `z.number()` plus `register(..., { valueAsNumber: true })`. Do NOT use `z.coerce.number()` — triggers type divergence with RHF 7 / Zod 4 / @hookform/resolvers 5 ("Two different types with this name exist" + "Type 'unknown' is not assignable to type 'number'").
- `isDirty` from RHF `formState` gates discard-confirm dialogs. Don't track dirty state manually.

## Build / tooling patterns

- Run `pnpm build` on every step, not just `pnpm dev`. Catches Suspense-around-`useSearchParams` and other issues dev mode tolerates.

## API client patterns

- Idempotency-Key generated inside the API client per-call (`crypto.randomUUID()` at request time), not at hook instantiation. Retry-after-500 produces two distinct intents.

## Design tokens (captured post Step 5.1.1)

Tokens live in `app/globals.css` (`@theme inline` block + `:root` / `.dark` blocks) and mirrored as TypeScript constants in `lib/design-tokens.ts`. Use the tokens; don't introduce ad-hoc colors, sizes, or radii.

**Tailwind v4 class-name collision watch:** every `--color-{name}` declared in `@theme inline` auto-generates `text-{name}` / `bg-{name}` / `border-{name}` color utilities. Do NOT name a custom `@utility` the same as an auto-generated color utility, even if the custom utility only sets non-color properties. Both rules emit `.text-{name}` and the cascade order is unpredictable, so the auto-generated color rule can clobber the typography intent (or vice versa). Discovered after a `text-secondary` typography utility silently lost the cascade to the `--color-secondary` color utility, painting subtitles at near-black on dark bg. Fix was to rename the typography utility to `text-caption`.

**Typography scale** (Tailwind v4 `@utility` classes; combine with a color class as needed):

| Class | Size / line-height | Weight | Use |
|---|---|---|---|
| `text-display` | 24/32 | 600 | Page titles (one per page) |
| `text-heading` | 18/24 | 600 | Section headers within a page |
| `text-subheading` | 15/22 | 600 | Card titles, drawer titles |
| `text-body` | 14/20 | 400 | Default body text |
| `text-body-strong` | 14/20 | 500 | Emphasized inline body |
| `text-caption` | 13/18 | 400 | Captions, table cells secondary, helper text |
| `text-label` | 12/16 | 500 + uppercase + tracking-wide | Form labels, table column headers |
| `text-micro` | 11/14 | 400 | Timestamps, tertiary metadata |

**Spacing semantics** (use the named Tailwind classes; constants in `lib/design-tokens.ts`):

- Page outer padding: `p-6`
- Between page sections: `gap-6` / `space-y-6`
- Card internal: `p-4`
- Inside-card gap: `gap-3`
- Table row vertical: `py-3`
- Form field stack: `gap-4`
- Icon + label inline: `gap-2`

**Colors**: prefer semantic Tailwind classes that resolve to tokens (`bg-background`, `bg-surface`, `bg-surface-raised`, `text-foreground`, `text-foreground-muted`, `text-foreground-subtle`, `border-border`, `border-border-strong`, `text-primary`, `bg-primary`, `text-success`, `text-warning`, `text-danger`, `text-info`). Avoid ad-hoc `text-zinc-*`, `bg-slate-*`, `border-gray-*` classes; status-meaningful chips that use hue-as-semantic (`emerald`, `amber`, `red`) are an established v0 pattern that stays.

**Border radius**: `rounded-sm` (2px badges/chips), `rounded` (4px buttons/inputs), `rounded-md` (6px cards/modals/drawers). Pills (`Badge`) use `rounded-full`. No `rounded-lg`/`rounded-xl` unless deliberate emphasis.

**Shadow elevation**: cards have `border` not `shadow`. Dropdowns get `shadow-sm`. Modals/drawers get `shadow-md`. Three tiers; no glows.

## Theme system (captured post Step 5.1.2)

- `next-themes` `ThemeProvider` is wired in `app/providers.tsx` (`attribute="class"`, `defaultTheme="system"`, `enableSystem`, `storageKey="ithina-theme"`, `disableTransitionOnChange`). User choice (Light / Dark / System) persists in localStorage; `<html>` gets the `dark` class added/removed by next-themes. `<html suppressHydrationWarning>` is set in `app/layout.tsx` to absorb the class-mismatch warning that arises from server-rendered HTML having no class until client hydration applies it.
- Theme radio in `components/chrome/UserMenu.tsx` uses `useTheme()` from next-themes. Three options: Light / Dark / System. Switching applies immediately.
- Sonner toaster (`components/ui/sonner.tsx`) reads `useTheme()` and forwards to Sonner's `theme` prop, so toasts theme automatically.
- Adding a new themeable color: define both light value in `:root` and dark value in `.dark` of `app/globals.css`, then map `--color-{name}: var(--{name})` in the `@theme inline` block. Tailwind v4 auto-generates `text-{name}` / `bg-{name}` / `border-{name}` utilities.
- **Chip / pill light-mode recipe pattern:** light base classes + `dark:` overrides on the same element. Light is `bg-{hue}-50 text-{hue}-700 ring-{hue}-200`; dark is `dark:bg-{hue}-500/15 dark:text-{hue}-300 dark:ring-{hue}-500/30`. Dot indicators use `bg-{hue}-600 dark:bg-{hue}-400`. Greyscale family uses `bg-zinc-100 text-zinc-700 ring-zinc-300` light + dark mirrors. The `dark:` prefix activates via the `@custom-variant dark (&:is(.dark *))` declaration in `globals.css`.

## Animation system (captured post Step 5.1.3)

Aesthetic anchor: Linear / Stripe Dashboard. Moderate, deliberate, restrained. Animations confirm user actions and orient them in space; they are not decoration. `prefers-reduced-motion` is respected globally.

**Duration tokens** (CSS vars in `:root` of `globals.css`; theme-agnostic):

| Token | Value | Use |
|---|---|---|
| `--duration-instant` | 100ms | Button press micro-feedback |
| `--duration-fast` | 150ms | Hover states, dropdown menus |
| `--duration-normal` | 200ms | Modal enter/exit, card transitions, filter-tab slide |
| `--duration-slow` | 280ms | Drawer slide, larger spatial moves |

Tailwind's built-in `duration-100`/`-150`/`-200`/`-300` utilities cover most cases. For 280ms, use `duration-[280ms]` arbitrary value.

**Easing tokens** (override Tailwind's defaults):

| Token | Value | Use |
|---|---|---|
| `--ease-out` | `cubic-bezier(0.16, 1, 0.3, 1)` | Elements entering (modal open, drawer slide in, optimistic insert) |
| `--ease-in` | `cubic-bezier(0.7, 0, 0.84, 0)` | Elements leaving (modal close, drawer slide out) |

Don't use `ease-in-out` for content-entering animations; out-expo for in, in-expo for out.

**`prefers-reduced-motion`:** global CSS rule at the bottom of `globals.css` sets `animation-duration` / `transition-duration` to `0.01ms !important` when the OS preference is set. Framer Motion respects the same preference via `<MotionConfig reducedMotion="user">` wrap in `app/providers.tsx`. Test by toggling OS setting or browser dev tools (Rendering panel → Emulate CSS media feature `prefers-reduced-motion: reduce`).

**Where animation lives in this codebase:**

- **Modal / drawer / dropdown enter+exit:** `tw-animate-css` utilities (`data-open:animate-in`, `fade-in-0`, `zoom-in-95`, `slide-in-from-*`, plus mirror `data-closed:` halves) on the shadcn primitives. Note: this codebase uses base-ui's `data-open:` / `data-closed:` boolean attributes, not Radix's `data-[state=open]:` selectors. When porting Radix-style snippets, translate the syntax.
- **Filter tab active-indicator slide:** base-ui `<TabsIndicator />` in `components/ui/tabs.tsx`. Renders absolutely positioned inside `<TabsList>`; base-ui sets `--active-tab-{left,top,width,height}` CSS variables; the indicator's Tailwind arbitrary-value classes pick those up and `transition-[left,top,width,height] duration-200 ease-out` makes it slide. Consumers must include `<TabsIndicator />` as a child of `<TabsList>` to get the slide.
- **Optimistic insert + layout shift:** `framer-motion` `<motion.div layout>` on `components/tenants/TenantCard.tsx` plus `<AnimatePresence>` wrapping the card grid in the Tenants page. New cards fade+translate-up on enter; existing cards reflow with smooth layout transitions. Future Phase 4c write flows follow the same pattern.
- **Skeleton shimmer:** `@keyframes shimmer` + `@utility skeleton-shimmer` in `globals.css`. Reduced-motion disables the keyframe via the global rule.
- **Hover states:** `transition-colors duration-150 ease-out hover:bg-surface-raised hover:border-border-strong` on cards and rows. Subtle bg + border shift; no lift, no shadow.
- **Button press:** `active:scale-[0.98] transition-transform duration-100 ease-out` baked into the `default` variant only. Skipped for outline / ghost / destructive / link / icon.

## Tier 1 closeout patterns (captured post Step 5.1.4)

- **`+N` overflow chip pattern.** When a horizontal pill list exceeds N items, render the first N pills then a `+{count - N}` chip in the same recipe but slightly muted. TenantCard uses N=4: `tenant.modules.slice(0, 4)` plus `+{tenant.modules.length - 4}` chip with `bg-zinc-100/60` (light) / `bg-zinc-500/5` (dark) and `text-zinc-600` / `text-zinc-400`. Drawer (or detail view) always shows the full list. Slice respects fixture order; do not re-sort to fit a "best N" subset. Hover/click on the +N chip is non-interactive in v0.
- **Type-to-confirm destructive dialog.** Use `<ConfirmDestructive>` from `components/shared/ConfirmDestructive.tsx` for any destructive action (suspend / terminate / delete / revoke). Props: `open`, `onOpenChange`, `title`, `description`, `confirmText` (string user must type), `confirmLabel`, optional `cancelLabel`, optional `destructive` (default true), `onConfirm` (sync or async). Match is case-sensitive with whitespace trimmed both sides. Confirm button stays disabled until match. Async `onConfirm` triggers a "Working..." spinner; dialog closes on resolve. Reset of typed input lives in the `onOpenChange` close path (not a useEffect, to satisfy React 19's `set-state-in-effect` rule). Reference impl in `/dev/components`.
- **Sidebar keyboard shortcut.** `Cmd+\` (Mac) / `Ctrl+\` (Win/Linux) toggles sidebar collapse. Global `keydown` listener in `components/chrome/Sidebar.tsx`'s `useEffect`. Tooltip on the collapse/expand button shows the shortcut. localStorage persistence under `ithina_sidebar_collapsed` is unchanged. `TooltipProvider` is mounted once in `app/providers.tsx` so any future tooltip consumer works without ad-hoc wiring.

## Org Tree component (captured post Step 5.2.1)

`components/org/OrgTree.tsx` exports `OrgTreePane` (the right-column container). It renders a Linear / VS Code-style nested tree using three new primitives in the same directory:

- **`OrgTreeRow.tsx`** — recursive row component. Renders one node per call, then recursively renders children inside a `<ul role="group">` when expanded. Each row has: indent guides (ancestor columns + own-depth column with L/T shape), expand caret (or 16px spacer when no children), type icon, display name, type badge, code (right-aligned, monospace, muted), kebab dropdown (revealed on row hover).
- **`OrgNodeTypeIcon.tsx`** — lucide icon per node type with subtle color tint that matches the type's badge tone.
- **`OrgNodeTypeBadge.tsx`** — small chip per node type. 7-type mapping: TENANT/HQ → blue, BUSINESS_UNIT → violet, COUNTRY → teal, REGION → emerald, STORE → amber, DEPARTMENT → grey. Reuses the dark/light recipe pattern from `Chips.tsx` (uppercase + tracking-wide, ring-on-light + alpha-overlay-on-dark).

**Indent guide algorithm.** For a row at depth D, the row's indent area has `ancestorGuides.length === D - 1` ancestor columns plus 1 own-depth column. Each ancestor column shows a `border-l border-border` vertical line if its `ancestorGuides[i]` entry is `true`. The own-depth column renders as L (last child of parent: vertical line top-half + horizontal at middle) or T (not last: vertical full height + horizontal at middle). Recursion: `childAncestorGuides = depth === 0 ? [] : [...ancestorGuides, !isLastChild]` — root's children get `[]` (no ancestor columns at depth 1); deeper children extend the array by appending the parent row's lineage status. Visual: the line at column K passes through descendants of an ancestor at depth K+1 IFF that ancestor is not the last child of its parent. Matches VS Code / Linear visual.

**Default expansion.** Top two levels (depth 0 + depth 1) auto-expanded; deeper levels collapsed. Implementation: `expanded` Set is `useMemo`'d from `roots` + `userToggled` Map. Default is `depth <= 1` per node; user clicks override per-node via the Map. Avoids `set-state-in-effect` because `expanded` is computed during render, not stored as state.

**Adding a new node type.** Extend `OrgNodeType` in `types/api.ts`, add the icon mapping in `OrgNodeTypeIcon.tsx`, add the recipe + label in `OrgNodeTypeBadge.tsx`. Three small edits, no further changes needed.

## Permission Matrix component (captured post Step 5.2.2)

`components/roles/PermissionMatrixView.tsx` is the top-level. Two helper components in the same directory:

- **`PermissionMatrixGroup.tsx`** — one resource group: optional module divider row + group header row (caret + resource name + count, click-to-toggle) + permission rows when expanded.
- **`PermissionMatrixRow.tsx`** — one permission row: sticky-left permission cell (`action · scope`) + N role cells (one per role in the active audience tab).

**Data shape.** Permissions are 4-tuples of `(module, resource, action, scope)`. Each role carries a `permission_ids: string[]` array. A cell is "granted" iff `role.permission_ids.includes(permission.id)`.

**Grouping strategy.** First pass collects groups keyed by `${module}:${resource}` preserving fixture insertion order; second pass buckets by module; final flatten respects `MODULE_ORDER` (Admin → Pricing OS → Perishables → Promotions → ROOS → Goal Console). Module dividers render above the first resource of each module via a `prevModule !== currentModule` check in the parent's iteration.

**Sticky header pattern.** CSS Grid would also work but `<table>` with `position: sticky` is cleaner. Three z-index tiers under a single `overflow-auto` scroll container:
- **Corner cell** (top-left "Permission" header): `sticky top-0 left-0 z-30`
- **Top header row** (role names): `sticky top-0 z-20`
- **Left column** (permission row labels, rendered as `<th scope="row">`): `sticky left-0 z-10`

Bg colors must be set explicitly on every sticky cell (otherwise scrolled content shows through). Use `bg-card` on header cells, `bg-card` or `bg-muted/20` on row labels (matching the row's zebra state).

**Default expansion.** Initial `expanded` Set seeded with the canonical first-group key (e.g., `"ADMIN:TENANTS"`). User toggles add/remove from the Set. Re-keying the matrix container by `audience` makes scroll position reset cleanly when switching tabs without manual scroll-to-top.

**Per-cell tooltip.** Wraps each cell's content (granted circle or empty) in `<TooltipTrigger render={<div className="flex h-8 w-full items-center justify-center" />}>` so hover anywhere in the cell area triggers. Tooltip text is `${module}.${resource}.${action}.${scope}`. ~450 wrapped cells across the full matrix; React perf tested fine since collapsed groups don't render rows. `TooltipProvider` from `app/providers.tsx` (mounted in 5.1.4) is required.

## Deploy flow (captured post Step 6.1)

The dev environment ships from a local `deploy-dev.sh` script that builds a Docker image, pushes to Artifact Registry, and rolls a new Cloud Run revision. The whole flow is solo-dev-friendly; Cloud Build / GitHub Actions automation comes later.

**Two tools, two concerns.** Image is gcloud-rolled; env vars are terraform-owned.

- **`deploy-dev.sh`** runs `gcloud run deploy --image=$TAG ...` and nothing else. It does not pass `--set-env-vars` / `--update-env-vars` / `--clear-env-vars`. Doing so would inject vars that terraform reverts on the next `apply`, because the service's `lifecycle.ignore_changes` block in `envs/dev/main.tf` covers the `image` field only.
- **Terraform** (`envs/dev/main.tf`) owns the `runtime_env` map: `NODE_ENV`, `API_BASE_URL`, `AUTH_MODE`, `DEV_JWT_MAP`, plus anything else the runtime needs. These are non-prefixed (server-only) and read at request time, so changing the backend URL, the auth mode, or a dev JWT is an env edit plus a revision bounce, not a rebuild.

**Backend wiring (post Phase 5n.1, 2026-05-18).** MSW was removed wholesale. The backend base URL is required; absence throws at the first call site. There is no relative-path fallback and no MSW boot path. Surfaces without backend coverage render empty states (BUILD_PLAN Finding #29). As of the runtime-config decoupling the base URL is `API_BASE_URL` (runtime, non-prefixed), not the old build-inlined `NEXT_PUBLIC_API_BASE_URL`. `pnpm dev` reads it from `.env.local`; deployed builds get it from `runtime_env`. See "Runtime config" below.

**FeaturePending empty-state convention (post Phase 5n.4, 2026-05-18).** Surfaces whose backend hasn't shipped render `<FeaturePending surface="X" eta="..." />` (from `components/shared/FeaturePending.tsx`) inside the normal page wrapper (`PageHeader` for Ithina, `FleetPageShell` for DIS). The stub is a minimal centered text + ETA — no decorative cards, no skeleton loaders pretending data is coming, no preserved mock data structures. Half-life is short (Admin APIs ~2 days, DIS APIs ~15 days). When the backend ships, REPLACE the FeaturePending stub with the real hook + render path — do NOT keep the dead data flow around for design refinement. Removal of FeaturePending happens per-surface in the chunk that wires that surface's real endpoint.

**Standalone build requires copying three locations.** `output: "standalone"` in `next.config.ts` emits `.next/standalone/` (with `server.js` and a minimal `node_modules` subset), but does NOT include `.next/static/` or `public/`. The runner stage of the Dockerfile must copy all three:

```
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
```

`HOSTNAME=0.0.0.0` env var is required in the runner stage; the standalone server defaults to localhost which Cloud Run can't reach.

**Runtime config (decoupled from build time).** The API base URL, auth mode, and dev persona JWTs are RUNTIME config, read server-side at request time, not inlined into the client bundle at `pnpm build`. (There is no `lib/auth/mint.ts` and no server-side RS256 mint; the JWTs are pre-minted and dispensed.) Two `force-dynamic` route handlers bridge non-prefixed server env to the client:

- **`app/api/config/route.ts`** returns `{ apiBaseUrl, authMode }` from `API_BASE_URL` / `AUTH_MODE` (authMode defaults to `stub`). `lib/config/runtime-config.ts` fetches this once on the client (`ensureRuntimeConfig`, deduped + cached) and exposes sync `getApiBaseUrl()` / `getAuthMode()` plus a `useRuntimeConfig()` hook; server callers read `process.env` directly with no round-trip. `apiFetch` awaits `ensureRuntimeConfig()` before resolving the URL, so its signature and callers are unchanged and the base URL is never raced.
- **`app/api/dev-token/route.ts`** returns the JWT for `?persona=<id>` from `DEV_JWT_MAP` (JSON object: persona id to JWT). It serves ONLY in `stub`/`dev` auth modes (404 otherwise), so a token-dispensing route never exists in a real build, and validates the persona against `lib/auth/personas.ts`. `getAuthToken()` stays synchronous by reading a module-level cache that `prefetchAuthToken()` warms on persona set and on initial load; `AuthBoundary` waits on resolution rather than bouncing to `/dev/login`.

`force-dynamic` on both routes is load-bearing: without it Next.js could prerender the GET at build time and re-freeze the env values, which is the exact build-time coupling this design removes. Adding a token for an existing persona is config-only (edit `DEV_JWT_MAP`, bounce the revision); no `NEXT_PUBLIC_` value carries a JWT, the API base, or the auth mode anymore.

**Image architecture.** Default amd64 (matches the x86_64 dev host). Apple Silicon developers must add `--platform linux/amd64` to the `docker build` line in `deploy-dev.sh`, otherwise Cloud Run rejects the arm64 image.

**Roll back.** `gcloud run revisions list --service=admin-frontend --region=asia-south1` to find a previous revision, then `gcloud run services update-traffic admin-frontend --to-revisions=<rev>=100 --region=asia-south1`. See `DEPLOY.md` for full commands.

