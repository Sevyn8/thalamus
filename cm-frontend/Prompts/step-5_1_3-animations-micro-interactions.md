# Step 5.1.3 — Animations + Micro-Interactions

## Context and intent

5.1.1 shipped the token foundation; 5.1.2 added light theme + system-aware toggle. The build looks deliberate now in both themes. What's missing is the "feels alive" layer: modals snap into place, cards don't respond to hover, filter tab switches are instant, optimistic inserts pop into the list without grace.

This step adds the animation polish. Calibration target: **Linear / Stripe Dashboard**. Moderate animation; 200ms transitions; deliberate easing curves; confident polish without decoration. Not Salesforce Lightning's minimal animation (would feel underbaked); not Notion's spring-physics expressive style (out of character with the utilitarian aesthetic).

`prefers-reduced-motion` is respected throughout. Users who opt out of motion get instant transitions or none at all, never a blocked or broken UI.

This is the third of four Tier 1 polish steps. Final polish (+N overflow, type-to-confirm, card density, sidebar discoverability) lands in 5.1.4.

## Aesthetic anchor: Linear/Stripe-style animation

Concrete reference points:

- **Duration:** 150-200ms for most transitions. 300ms for larger/spatial moves (drawer slide, modal enter). Anything over 300ms feels sluggish.
- **Easing:** `cubic-bezier(0.16, 1, 0.3, 1)` (out-expo) for elements entering. `cubic-bezier(0.7, 0, 0.84, 0)` (in-expo) for elements leaving. Standard `ease-out` works for hover states. No `ease-in-out` for entries — feels heavy.
- **Hover states:** subtle. Cards gain a `border-strong` color shift and 2-4% background lighten on hover, no lift/translate. Buttons may gain 10% darker bg. Rows in tables/lists gain `bg-surface-raised`.
- **Loading states:** skeleton shimmer (gentle gradient sweep, 1.5s loop), not pulse. Crossfade to real content (200ms) when data arrives.
- **Optimistic inserts:** new item fades in from 0 to 100% opacity over 200ms with a tiny 4px translate-up. Doesn't bounce. Doesn't shimmer. Just lands.
- **Filter tab transitions:** active indicator (an underline or pill background) slides between positions over 200ms. Click feels reactive.
- **Modal/drawer:** modal scales from 96% to 100% with fade-in, 200ms. Drawer slides from right, 280ms. Backdrop fades 200ms. Exit reverses.

The principle: **animations confirm the user's action and orient them in space**. They are not decoration. Every animation has a job — confirming a click, showing where new content arrived from, indicating loading. If you can't justify an animation's job, drop it.

## Acceptance criteria

1. Modal enter/exit animations land. Provision Tenant modal scales-and-fades on open, reverses on close. Backdrop fades. Animation respects `prefers-reduced-motion`.
2. Drawer enter/exit animations land. Tenant detail drawer slides from right, content fades in. Reverses on close. Backdrop fades.
3. Dropdown menu enter/exit animations land. Profile menu, kebab menus (when added in Phase 4c), filter dropdowns. Quick fade + slight scale, 150ms.
4. Toast enter/exit animations land. Success/error toasts slide in from a corner (sonner default but verify duration matches our system).
5. **Card hover states** across the app: tenant cards, KPI cards, top-tenants rows, recent-activity rows, audit log rows, user table rows, role catalog rows, module access rows. Hover gains a subtle background or border shift. 150ms.
6. **Filter tab active-indicator transition.** When user clicks a tab, the active indicator slides between positions rather than jumping. Applies to Tenants page tier filter, audit log result filter, and any other tab-based filter in the build.
7. **Optimistic insert animation.** When a new tenant is provisioned (or any future create flow), the new card fades + translates 4px up into the list over 200ms. Existing cards shift to make room with a 200ms easing.
8. **Loading skeleton shimmer.** Replace static skeleton placeholders with a gentle shimmer gradient that loops every 1.5s. When real data arrives, content crossfades in over 200ms.
9. **Sidebar nav item hover.** Active page indicator already exists; add a hover state for inactive items (subtle bg + foreground shift, 150ms). Don't animate the active indicator itself jumping between items — that would conflict with Next.js navigation.
10. **Button micro-interactions.** Primary buttons (e.g., "Provision tenant" submit) gain a subtle press state on click (1-2% scale-down for 100ms). Don't add to ghost buttons or kebab triggers — too noisy.
11. **`prefers-reduced-motion` respect.** Add CSS rule `@media (prefers-reduced-motion: reduce)` that sets transition-duration to ~0.01ms and removes transform animations. Test by enabling "Reduce motion" in OS settings and verifying every animated element renders cleanly without motion.
12. The 8 pages still render with the same content, behavior, and theming. No layout restructures.
13. `pnpm tsc --noEmit` exits zero.
14. `pnpm lint` exits zero.
15. `pnpm build` succeeds.
16. No console errors (modulo activation race; pre-mark ⚠️).
17. BUILD_PLAN.md updated: Step 5.1.3 → DONE; Phase 5a entry shows 5.1.3 done, 5.1.4 remaining.
18. PATTERNS.md updated with an "Animation system" section: duration scale, easing tokens, where to use what, reduced-motion pattern.

## Animation token specification

Add to `app/globals.css` (or wherever 5.1.1 tokens live), under both `:root` and `.dark` (values are theme-agnostic — same in both):

### Duration scale

| Token | Value | Use |
|---|---|---|
| `--duration-instant` | `100ms` | Button press, micro-feedback |
| `--duration-fast` | `150ms` | Hover states, dropdown menus, small UI |
| `--duration-normal` | `200ms` | Modal enter/exit, card transitions, filter tabs |
| `--duration-slow` | `280ms` | Drawer slide, larger spatial moves |

No values above 300ms. Anything that needs longer than 300ms probably shouldn't be animated — either it's too big (rethink the interaction) or it doesn't need motion (use static).

### Easing curves

| Token | Value | Use |
|---|---|---|
| `--ease-out` | `cubic-bezier(0.16, 1, 0.3, 1)` | Elements entering (modal open, drawer slide in, optimistic insert) |
| `--ease-in` | `cubic-bezier(0.7, 0, 0.84, 0)` | Elements leaving (modal close, drawer slide out) |
| `--ease-standard` | `ease-out` | Default for hover/state changes; CSS keyword |

Don't use `ease-in-out` for content-entering animations. The "ease-in" half feels like the UI is reluctant. Out-expo for in, in-expo for out.

Expose as Tailwind utilities so components can write `transition-[transform,opacity] duration-normal ease-out` etc.

## Where to apply animations (concrete)

### Modal (`components/shared/Modal.tsx`)

Currently uses shadcn Dialog primitive. shadcn Dialog supports `data-[state=open]:animate-in` and `data-[state=closed]:animate-out` via Tailwind animation classes.

```tsx
// shadcn DialogContent (or wherever the modal panel renders)
<DialogContent className={cn(
  "data-[state=open]:animate-in data-[state=closed]:animate-out",
  "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
  "data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95",
  "data-[state=open]:duration-200 data-[state=closed]:duration-150",
  "data-[state=open]:ease-out data-[state=closed]:ease-in",
  // ... existing classes
)}>
```

Backdrop (DialogOverlay) gets just fade-in/out, 200ms. No scale.

If shadcn Dialog primitive in this codebase is already wired with these classes — just verify durations + easing match our tokens. Don't double-wire.

### Drawer (`components/shared/Drawer.tsx` / shadcn Sheet)

shadcn Sheet supports `slide-in-from-right` / `slide-out-to-right` via Tailwind animation utilities. Verify or apply:

```tsx
<SheetContent className={cn(
  "data-[state=open]:animate-in data-[state=closed]:animate-out",
  "data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right",
  "data-[state=open]:duration-280 data-[state=closed]:duration-200",
  // ... existing classes
)}>
```

Drawer is wider than modal so 280ms feels right; 200ms feels rushed for the larger spatial move.

### Card hover (Tenant cards, KPI cards, list rows)

Each clickable card/row gets:

```tsx
className={cn(
  // existing
  "transition-colors duration-150 ease-out",
  "hover:bg-surface-raised hover:border-border-strong",
)}
```

`bg-surface-raised` is the token from 5.1.1 (slightly lighter than surface). `border-border-strong` is more pronounced than the default. Subtle visual feedback that the row is interactive without lifting/shadowing.

For tenant cards specifically (which are larger surfaces): same pattern but consider a slightly more pronounced shift since they have more visual weight. Test in browser; nudge the values if hover doesn't read.

### Filter tab active-indicator

shadcn Tabs primitive, by default, doesn't animate the active indicator between tabs. Two ways to add it:

**Approach A: Framer Motion's `layoutId`.** Wrap the active indicator in `<motion.div layoutId="active-tab" />`. When the active tab changes, motion magically animates the indicator to its new position. ~5 lines, very clean. Adds Framer Motion dependency if not already present.

**Approach B: CSS-only with sliding underline.** Use a ::after pseudo-element on the tab list parent, position calculated from the active tab's index. More complex but no dependency.

**My lean: A (Framer Motion).** Industry-standard, 4kB gzipped, the codebase will likely use it for other animations later anyway (sidebar collapse animation in 5.1.4, complex page transitions in future polish). Worth installing now.

Confirm before installing. If user prefers no new dependencies, fall back to B.

### Optimistic insert animation (Tenant card after Provision Tenant submit)

When `useProvisionTenant` mutation runs `onMutate` and prepends the optimistic placeholder to the list, the new card should animate in. Two layers:

1. **New card enter:** `<motion.div layout initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}>` (or CSS equivalent if not using Framer)
2. **Existing cards shift:** `layout` prop on the card components automatically animates layout changes. Existing cards smoothly move down to make room.

Without Framer Motion, the layout-shift animation is hard. Plain CSS `transition: transform` on cards in a CSS Grid doesn't fire on grid reflow. This is the strongest argument for installing Framer Motion.

If Framer Motion gets installed for filter tabs, this comes basically free.

### Loading skeleton shimmer

Replace the static skeleton in `components/shared/Skeleton.tsx` (or shadcn Skeleton) with a shimmer gradient:

```css
@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

.skeleton-shimmer {
  background: linear-gradient(
    90deg,
    var(--surface) 25%,
    var(--surface-raised) 50%,
    var(--surface) 75%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
}
```

Replace the existing skeleton's pulse animation with this. `prefers-reduced-motion` should disable the keyframes entirely (pure surface color, no animation).

### Crossfade skeleton → content

When data arrives, the skeleton placeholder needs to fade out as content fades in. With React Query's `isLoading` state:

```tsx
{isLoading ? (
  <SkeletonGrid />
) : (
  <div className="animate-in fade-in duration-200">
    <ContentGrid data={data} />
  </div>
)}
```

The `animate-in fade-in` Tailwind utility (from `tailwindcss-animate`, which shadcn ships with) handles this. Verify it's present.

### Sidebar nav item hover

```tsx
className={cn(
  "transition-colors duration-150 ease-out",
  "hover:bg-surface-raised hover:text-foreground",
  // active state classes already exist; don't change
)}
```

Hover only — don't animate the active state indicator. That would create motion every time the user navigates pages, which feels wrong.

### Button press micro-interaction

shadcn Button primitive in `components/ui/button.tsx`:

```tsx
className={cn(
  // existing variants
  "active:scale-[0.98] transition-transform duration-100 ease-out",
)}
```

Apply only to `default` and `primary` variants. Skip for `ghost`, `outline`, icon buttons — too noisy.

## `prefers-reduced-motion` implementation

Add to `app/globals.css` at the top level (not inside a theme):

```css
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

This is the canonical pattern. It nukes all animation/transition durations to effectively zero without breaking layouts.

If using Framer Motion, also wrap the app in:

```tsx
<MotionConfig reducedMotion="user">
  {children}
</MotionConfig>
```

This makes Framer Motion respect the OS preference automatically; without it, Framer animations bypass the CSS rule above.

Test by enabling "Reduce motion" in macOS Settings → Accessibility → Display, or in browser dev tools (Rendering panel → Emulate CSS media feature `prefers-reduced-motion`). Every animation should become instant. UI should remain functional.

## Files modified

Likely:
- `app/globals.css` (animation tokens, reduced-motion rule, skeleton shimmer keyframes)
- `tailwind.config` or v4 inline config (expose duration/easing as Tailwind utilities)
- `app/providers.tsx` (MotionConfig wrap if using Framer)
- `components/ui/dialog.tsx` (modal animation classes — verify or apply)
- `components/ui/sheet.tsx` (drawer animation classes)
- `components/ui/button.tsx` (press state)
- `components/ui/dropdown-menu.tsx` (verify enter/exit animation)
- `components/shared/Skeleton.tsx` (shimmer)
- `components/tenants/TenantCard.tsx` (hover, optimistic insert wrapper)
- `components/tenants/ProvisionTenantModal.tsx` (verify modal animation lands)
- `components/dashboard/KpiCard.tsx`, `TopTenantsPanel.tsx`, `RecentActivityPanel.tsx` (hover states on rows)
- `components/users/UsersTable.tsx` (row hover)
- `components/audit/AuditTable.tsx` (row hover)
- `components/chrome/Sidebar.tsx` (nav item hover)
- Any tabs implementation (Tenants tier filter, audit result filter) — Framer Motion `layoutId` integration
- `package.json` (if Framer Motion: add)
- `BUILD_PLAN.md`, `PATTERNS.md`

Estimated diff size: 30-50 files. Most are 1-3 line additions (transition + duration + easing classes on hover targets). Framer Motion integration touches maybe 4-5 files meaningfully.

## Smoke checklist

After implementing:

1. **Modal animations.** Click "+ Provision tenant" → modal scales+fades in over ~200ms. Click cancel → reverses. Backdrop fades. Click escape → same.
2. **Drawer animations.** Click a tenant card → drawer slides in from right over ~280ms. Click X → reverses.
3. **Dropdown menus.** Click profile avatar → menu fades+scales in quickly (~150ms). Click outside → reverses.
4. **Card hover states.** Hover a tenant card → subtle bg/border shift, no jump. Hover KPI card → same. Hover audit log row → row highlights. Each hover is responsive (~150ms).
5. **Filter tabs.** On Tenants page, click between All / Enterprise / Mid-Market → active indicator slides between tabs. On Audit Log, same with result tabs.
6. **Optimistic insert.** Submit Provision Tenant form → new card fades+translates into place over ~200ms. Existing cards shift down smoothly. (This is the most visible animation.)
7. **Loading skeleton.** Hard reload page → skeleton shimmer is visible, not static. When data arrives, skeleton fades to content.
8. **Sidebar nav hover.** Hover an inactive nav item → bg shift. Active item unchanged.
9. **Button press.** Click "Provision tenant" submit → subtle scale-down. Click cancel → no press effect (ghost button).
10. **Reduced motion.** Enable "Reduce motion" in OS or browser dev tools → reload. Repeat steps 1-9. Every animation should be instant. UI should be fully functional. No element should be stuck offscreen / invisible / mid-animation.
11. Both themes still render correctly (5.1.2 didn't regress).
12. Console clean modulo activation race.
13. `pnpm build` succeeds.

## Process notes

- Pre-mark "no console errors" as ⚠️ (activation race).
- Pre-smoke self-check before browser smoke. Verify reduced-motion rule is at the top of globals.css (high specificity), Framer MotionConfig is wrapped if used, all duration/easing tokens are exposed as Tailwind utilities.
- The Framer Motion install decision is the biggest call. Surface up front. Without it, filter-tab indicator and optimistic-insert layout shift are notably harder.
- If a hover state feels "too much" (e.g., card lifts/jumps), back it off — Linear/Stripe animations are restrained. The principle is "subtle confirmation," not "look at me."
- If an animation feels "too slow," check the easing curve before changing duration. Out-expo at 200ms feels faster than ease-in-out at 200ms because most of the motion happens early.
- Test `prefers-reduced-motion` early, not late. It's the most-skipped acceptance criterion in animation work, and discovering an issue at the end means re-walking the whole app.

## Ask before building

Things worth surfacing upfront:

- **Framer Motion install.** Confirm before adding. If user wants to avoid the dependency, switch filter-tab indicator and optimistic-insert layout-shift to CSS-only approaches (more work, more limited).
- **shadcn animation utilities present?** Check whether `tailwindcss-animate` (the package shadcn uses for `animate-in`, `fade-in`, `slide-in-from-right`, etc.) is installed. If not, install. If yes, verify the existing modal/drawer/dropdown components reference these utilities or whether they need to be retrofitted.
- **Existing Sidebar localStorage state.** If user's `ithina_sidebar_collapsed` is still set to "1", animations on nav items won't be visible because the sidebar shows icons-only. Note in smoke that user may want to expand sidebar first to see nav hover states.
- **Reduced-motion testing.** Confirm user has a way to test (macOS / Windows / Linux all have OS-level toggles, plus browser dev tools support). If user can't test, manually verify the CSS rule is correct via dev tools forced state.

Post the pre-smoke self-check structured table when ready, same shape as v0 + 4.1 + 5.1.1 + 5.1.2 steps. After smoke passes, propose the commit. Expected commit message:

> Step 5.1.3: Animations + micro-interactions
>
> Linear/Stripe-calibrated polish. Modal/drawer/dropdown enter/exit animations. Card hover states across 8 pages. Filter tab active-indicator slide. Optimistic insert with layout shift. Skeleton shimmer + crossfade to content. Button press micro-feedback. Sidebar nav hover.
>
> Animation duration + easing tokens canonicalized (4 durations, 3 easings).
>
> `prefers-reduced-motion` respected globally; every animated element falls back to instant transition under user opt-out.
>
> Build now feels alive. 5.1.4 remains: +N overflow, type-to-confirm, card density, sidebar discoverability.
