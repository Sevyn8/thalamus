# Step 5.1.2 — Light Mode + Theme Toggle

## Context and intent

5.1.1 shipped the design token foundation: typography scale, spacing, color palette (dark variant refined), border-radius, shadow elevation. Subtitles render correctly. The build feels meaningfully more deliberate.

This step adds the light theme as a peer to dark, with a working toggle. Default initial state is OS preference (`prefers-color-scheme`); user choice persists via localStorage and overrides OS preference on subsequent visits. Both themes feel intentional, neither is an afterthought of the other.

This is the second of four Tier 1 polish steps. Animations come in 5.1.3, final polish (+N overflow, type-to-confirm, card density) in 5.1.4.

## Aesthetic anchor: Salesforce-adjacent enterprise B2B admin (light variant)

For light mode, the calibration target shifts:

- **Background:** near-white off-grey (`#FAFAFA` / oklch ~0.98). Not pure white — pure white can feel sterile against the saturated chrome.
- **Surfaces (cards, drawers, modals):** pure white (`#FFFFFF` / oklch 1.00). Surfaces should be visibly raised against the page background, even with subtle borders.
- **Foreground:** very dark grey (`#0F1115` / oklch ~0.15), not pure black. Pure black on white is too high contrast for sustained reading.
- **Borders:** soft but present (`#E5E7EB` / oklch ~0.91). Visible enough to define cards/inputs/dividers.
- **Primary:** the same blue (`#3B82F6` / oklch ~0.62). Cross-theme color consistency is correct — primary blue should look like the same brand color in both themes.
- **Status colors:** retain semantic meaning, but sometimes need tonal adjustment (success green at the dark-theme oklch can look too neon on light; nudge toward a darker value if so).

Reference targets: Stripe Dashboard, Linear (light mode), Notion, Salesforce Lightning. All four use white surfaces on near-white backgrounds, soft borders, and reserve color for status/CTA only.

## Acceptance criteria

1. `app/globals.css` defines a complete light theme variant. Every CSS custom property defined for dark in 5.1.1 has a paired light value. Light is the default `:root` selector; dark is under `.dark` selector (matching shadcn convention).
2. **Theme toggle in profile menu.** Profile dropdown (top-right avatar menu, already stubbed in v0 chrome) gets a "Theme" submenu or section with three options: Light / Dark / System. The current selection is checked. Switching applies immediately without page reload.
3. **System detection on first visit.** When no localStorage value exists, theme matches `window.matchMedia('(prefers-color-scheme: dark)')`. Updates live if the user changes their OS preference while the app is open (only when "System" is the selected option, not when user has explicitly picked Light or Dark).
4. **Persistence.** User choice (Light, Dark, or System) saves to localStorage under a single key (`ithina-theme`). Persists across sessions. Initial render reads localStorage; if absent, defaults to "System".
5. **No flash of unstyled / wrong-themed content (FOUC) on initial load.** A blocking inline script in the document `<head>` reads localStorage and applies the `dark` class to `<html>` before React hydrates. Alternatively, use Next.js `next-themes` package which handles this canonically. Either works; pick one and document choice.
6. **Both themes feel intentional, not just inverted.** Walk all 8 pages in light mode. Adjust any token whose dark value translates poorly to light (e.g., status chip backgrounds may need different opacity in light; muted foregrounds need different luminance in light to maintain ~5:1 contrast).
7. Cards, inputs, drawers, modals, dropdowns, toasts, dialogs all render correctly in both themes. No element renders with hardcoded dark-theme values that survive a theme switch.
8. **Chips/badges remain visible in both themes.** Status chips (Active green, Trial amber, Suspended red), tier chips, action chips. The dark-mode `bg-{hue}-500/15` pattern (15% opacity overlay) translates to light differently — at low alpha on white, the chip becomes invisible. Adjust to `bg-{hue}-500/10` plus a stronger ring/border, or shift to a different chip recipe per-theme.
9. The 8 pages still render with the same content and behavior in both themes. No layout restructures.
10. `pnpm tsc --noEmit` exits zero.
11. `pnpm lint` exits zero.
12. `pnpm build` succeeds.
13. No console errors (modulo the pre-existing activation race; pre-mark ⚠️).
14. BUILD_PLAN.md updated: Step 5.1.2 → DONE; Phase 5a entry shows 5.1.2 done, 5.1.3/5.1.4 remaining.
15. PATTERNS.md updated with a "Theme system" section: how the toggle works, where the localStorage key lives, FOUC prevention pattern, how to add a new themeable token.

## Light theme token specification

Pair every dark value with a light counterpart. Where shadcn already provides defaults, refine those values rather than introducing parallel tokens.

### Color palette (light variant — under `:root`)

| Token | Light value | Notes |
|---|---|---|
| `--background` | `oklch(0.98 0 0)` ≈ `#FAFAFA` | Page background |
| `--surface` | `oklch(1.00 0 0)` ≈ `#FFFFFF` | Cards, drawer, modal |
| `--surface-raised` | `oklch(0.97 0 0)` ≈ `#F5F5F5` | Hover state, popovers |
| `--foreground` | `oklch(0.15 0 0)` ≈ `#0F1115` | Primary text (not pure black) |
| `--foreground-muted` | `oklch(0.40 0 0)` ≈ `#5C5F65` | Subtitles, secondary cells, helper text. Target ~5:1 against `--background`. |
| `--foreground-subtle` | `oklch(0.55 0 0)` ≈ `#7C8085` | Tertiary metadata, placeholders. Target ~3.5:1. |
| `--border` | `oklch(0.91 0 0)` ≈ `#E5E7EB` | Default borders |
| `--border-strong` | `oklch(0.83 0 0)` ≈ `#CFD2D7` | Emphasized borders, focus rings |
| `--primary` | `oklch(0.62 0.19 257)` ≈ `#3B82F6` | Same blue as dark — cross-theme brand consistency |
| `--primary-foreground` | `oklch(1.00 0 0)` ≈ `#FFFFFF` | Text on primary |
| `--success` | `oklch(0.60 0.18 162)` (slightly darker than dark variant) | Compensates for green looking neon on light |
| `--warning` | `oklch(0.72 0.17 65)` | |
| `--danger` | `oklch(0.58 0.22 25)` | |
| `--info` | `oklch(0.55 0.22 280)` | |

Verify each value against contrast standards using a tool (Stark, contrast-ratio.com, or eyeball with WebAIM contrast checker). Targets: foreground 7:1 (AAA), foreground-muted 5:1, foreground-subtle 3.5:1, primary on background 4.5:1.

### Borders, radius, shadow

Radius and typography scale are theme-agnostic — same values both themes.

Shadow values may need adjustment for light:
- `--shadow-sm` light: `0 1px 2px rgba(0,0,0,0.05)` — subtler than dark
- `--shadow-md` light: `0 4px 12px rgba(0,0,0,0.08)` — same principle

Light theme cards still use **borders, not shadows**, per Salesforce-adjacent. Shadows reserved for floating elements (dropdowns, modals).

## Theme toggle implementation

Two viable approaches:

**Approach A: `next-themes` package**

Mature, handles FOUC prevention, system detection, localStorage, all out of the box. Add to `app/providers.tsx` wrapping with `<ThemeProvider attribute="class" defaultTheme="system" enableSystem>`. Profile menu uses `useTheme()` hook for the toggle UI.

Pros: zero custom code for hard problems (FOUC, hydration mismatch, system listener). One dependency, well-maintained.

Cons: adds a dependency. Some projects prefer to roll their own for transparency.

**Approach B: Custom theme provider**

Write a small React context that:
- Initializes from localStorage (key `ithina-theme`), or `prefers-color-scheme` if absent
- Applies `dark` class to `<html>` element via `useEffect`
- Listens to `(prefers-color-scheme: dark)` media query for live system updates (only when "System" is selected)
- Adds blocking inline `<script>` to document `<head>` to apply class pre-hydration

Pros: no dependency, full control.

Cons: easy to get FOUC wrong, easy to get hydration warnings wrong, easy to miss the live-system-update edge case.

**My lean: Approach A (`next-themes`).** Solved problem, well-trodden, ~3kB gzipped. The custom approach is a real engineering exercise but for an enterprise admin console where theme toggle is table-stakes, not differentiator, ship the package and move on.

Surface the choice before building. If user confirms `next-themes`, install and integrate. If user prefers custom, write the provider with all four bullet points above and verify FOUC + hydration carefully.

## Theme toggle UI

Profile dropdown menu (top-right avatar, already in v0 chrome at `components/chrome/ProfileMenu.tsx` or similar). Add a "Theme" section:

```
┌──────────────────────────┐
│ Anjali Mehta             │
│ Super Admin              │
├──────────────────────────┤
│ 👤 Profile               │
│                          │
│ Theme                    │
│   ○ Light                │
│   ● Dark                 │
│   ○ System               │
│                          │
│ ↪ Sign out               │
└──────────────────────────┘
```

Three radio-style options. The current selection has a check or filled circle. Click switches immediately, no confirm. shadcn `DropdownMenuRadioGroup` is the right primitive.

If the existing ProfileMenu doesn't have an obvious slot for this, add a `<DropdownMenuSeparator />` and a `<DropdownMenuLabel>Theme</DropdownMenuLabel>` followed by the radio group.

## Cross-theme verification

After implementing, walk every page in both themes. The "look at it in both themes" step is what catches surfaces with hardcoded values, missed tokens, or wrong contrast. This is non-optional.

For each page, verify in light:
- Page title, subtitle, headers all readable
- Cards visibly raised against the page background (border or subtle elevation)
- Inputs have visible borders
- Filter tabs have a clear active state distinct from inactive
- Status chips remain readable (this is the most likely break — see chip section below)
- Drawer slides over and is visually distinct from page underneath
- Modal backdrop is visible (light backdrop should still dim the page)

For each page, verify in dark:
- Re-confirm 5.1.1 didn't regress
- Toggle from light → dark → light → system. State persists and feels instant.

## Chip-in-light-mode problem

This is the predictable surface that breaks. Dark-mode chips use the pattern:

```
bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30
```

15% green tint on dark background = visible. 15% green tint on white background = nearly invisible. The chip needs a different recipe in light mode.

Two fixes available:

**Fix A: Theme-conditional Tailwind classes**

```tsx
className={cn(
  "px-2 py-0.5 text-xs rounded-full ring-1",
  // light theme
  "bg-emerald-50 text-emerald-700 ring-emerald-200",
  // dark theme overrides
  "dark:bg-emerald-500/15 dark:text-emerald-300 dark:ring-emerald-500/30"
)}
```

Same chip component, two recipes via Tailwind's `dark:` prefix. shadcn-canonical pattern.

**Fix B: CSS variable per-status-per-theme**

Define `--chip-success-bg`, `--chip-success-fg`, `--chip-success-ring` as CSS variables, set per theme. Component reads from the variable. Cleaner separation of concerns; more verbose initial setup.

**My lean: Fix A.** shadcn pattern, zero new tokens, easier for future maintainers to understand. Apply to all chip variants in `components/shared/Chips.tsx`: status (active, trial, suspended), tier (enterprise, mid-market, smb, single-store), action (view, configure, execute, approve, override, audit), result (success, denied, pending), scope.

Surface to user if unsure; this is a real choice.

## Files modified

Likely:
- `app/globals.css` (light theme variant)
- `app/providers.tsx` or equivalent (ThemeProvider wrapping)
- `app/layout.tsx` (suppressHydrationWarning on html, possible inline FOUC script)
- `components/chrome/ProfileMenu.tsx` (theme toggle UI)
- `components/shared/Chips.tsx` (light-mode-aware chip recipes for all variants)
- `components/shared/Toaster.tsx` or `app/providers.tsx` (sonner toast theme prop wired to current theme)
- `package.json` (if Approach A: add `next-themes`)
- `BUILD_PLAN.md` (Step 5.1.2 → DONE)
- `PATTERNS.md` (Theme system section)

Possibly:
- Components with hardcoded dark colors that escaped the 5.1.1 sweep — discovered while walking pages in light mode. Fix in place.
- `mocks/handlers/*.ts` — no change expected (handlers are theme-agnostic).

Estimated diff size: 20-40 files. Smaller than 5.1.1's diff because the foundation is in place; this is mostly adding the light values + chip variants + toggle UI.

## Smoke checklist

After all changes:

1. Open `/superadmin/dashboard` for the first time in incognito (or clear localStorage). If OS is set to dark, page renders dark. If OS is light, page renders light. No FOUC.
2. Profile menu → Theme → Light. Page transitions to light immediately. Reload — still light.
3. Profile menu → Theme → Dark. Page transitions to dark. Reload — still dark.
4. Profile menu → Theme → System. Page matches OS preference. Change OS preference (System Settings or browser dev tools "Emulate prefers-color-scheme") — page updates live.
5. Walk all 8 pages in light theme:
   - Dashboard: KPI cards readable, top tenants panel readable, recent activity timestamps readable
   - Tenants: 7 cards visible, status/tier chips clearly visible, module pills clearly visible
   - Click tenant card → drawer opens in light theme, primary contact and modules sections readable
   - Click "+ Provision tenant" → modal opens in light theme, form fields and labels and help text all readable
   - Submit a tenant → success toast in light theme, optimistic insert visible
   - Users: table rows visible, role chips visible, MFA dot visible (green/red dot needs different contrast on light)
   - Org Tree: tree node hierarchy visible, node-type badges visible
   - Roles & Permissions: role catalog list readable, permission matrix legible
   - Module Access: matrix grid readable, toggle states clear
   - Guardrails: rule rows readable, status indicators clear
   - Audit Log: timestamp / actor / action / resource / scope / result columns all readable, result chips visible (especially "denied" red — common contrast trap on white)
6. Repeat the walk in dark theme — verify 5.1.1 polish didn't regress.
7. Walk in System theme with OS-dark — should look identical to "Dark" walk.
8. Walk in System theme with OS-light — should look identical to "Light" walk.
9. `/dev/components` demo page renders all primitives correctly in both themes.
10. Console clean modulo activation race.
11. `pnpm build` succeeds.
12. No hydration warnings in dev console (this is the common failure mode for theme implementations).

## Process notes

- Pre-mark "no console errors" as ⚠️ (activation race).
- Pre-smoke self-check before browser smoke. Verify light tokens defined for every dark token (no orphans), verify FOUC prevention is in place (inline script or `next-themes`), verify hydration mismatch handled (suppressHydrationWarning on `<html>` or matching the package's pattern).
- The chip variant change is the most error-prone part. Don't approve until every chip has been visually verified in both themes. Include screenshots if possible — even ad-hoc dev tool screenshots in the report.
- Hydration mismatch warning is a real failure: if `<html>` has `class="dark"` server-side and `class=""` client-side, React errors in console. `suppressHydrationWarning` on `<html>` is the canonical fix; verify it's there.
- If a status color (e.g., success green) looks too saturated in light mode after using the same value as dark, the right fix is theme-conditional adjustment, not changing the dark value. Light values can drift from dark for semantic colors.
- Don't add new pages. Don't add new components. Don't refactor existing components beyond what's needed for theming. Scope discipline: this step is light theme + toggle.

## Ask before building

Things worth surfacing upfront:

- **`next-themes` vs custom provider.** Confirm preference before installing/wiring.
- **Profile menu state.** Open the existing profile menu component. Is there a clear slot for the theme submenu, or does the menu need restructuring? If restructuring is needed, surface the change before doing it.
- **Chip recipe approach.** Confirm Fix A (Tailwind `dark:` variants) vs Fix B (per-theme CSS vars). Either works.
- **Chip color values in light.** The default Tailwind `emerald-50 / emerald-700 / emerald-200` family is the obvious starting point but may not match the dark-mode chip's perceived weight. Surface any that visually don't pair well with dark mode's recipe.
- **Toaster theming.** sonner accepts a `theme` prop. Confirm it gets wired to the current theme so toasts render correctly.

Post the pre-smoke self-check structured table when ready, same shape as v0 + 4.1 + 5.1.1 steps. After smoke passes, propose the commit. Expected commit message:

> Step 5.1.2: Light mode + system-aware theme toggle
>
> Light theme as peer to dark. System preference detected on first visit; user choice persists via localStorage. Toggle in profile menu (Light / Dark / System).
>
> Chip recipes adjusted for light visibility. Tokens cross-theme verified for contrast (foreground 7:1, foreground-muted 5:1).
>
> Both themes feel intentional. 5.1.1 dark polish preserved.
