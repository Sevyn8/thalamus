# Thalamus UI design spec — extracted from dis-ui-ver2

**Source of truth: `dis/services/dis-ui-ver2/`, and nothing else.**

This document is the standing UI playbook for Customer Master and any future Thalamus
frontend. Every value below is quoted from dis-ui-ver2's own code with `file:line`. Where a
pattern CM needs does not exist in ver2, this spec says so explicitly and derives a treatment
from ver2's tokens — it never falls back to `dis/services/dis-ui` (the older DIS frontend),
which is out of scope by decision.

ver2's own stylesheet header makes the same rule for itself
(`src/index.css:1-12`): *"DELIBERATE, recorded visual divergence from services/dis-ui …
Do NOT pull in dis-ui's Inter/oklch/Ithina-console look here."* This spec inherits that rule.

**Provenance of the source tree**, verified rather than assumed:
`infra/envs/staging/variables.tf:213-217` pins `dis-ui-ver2:v17` and names
`dis/terraform/docker/cloudbuild-dis-ui-ver2.yaml` as its builder; that cloudbuild builds with
`-f terraform/docker/dis-ui-ver2.Dockerfile` (`:74`) against context `services/dis-ui-ver2`
(`:64`). So the deployed service builds from the tree quoted here.

**Stack note.** ver2 is Vite + React Router + Tailwind v4 CSS-first (`@import 'tailwindcss'` +
`@theme`, no `tailwind.config.js`). CM is Next.js App Router, also Tailwind v4. The token
mechanism is therefore identical and ports directly; only font loading differs (§8).

---

## 1. Typography

**Families** — IBM Plex Sans and IBM Plex Mono, self-hosted via `@fontsource`, imported in
`src/main.tsx:8-14`:

```
@fontsource/ibm-plex-sans/400.css  500  600  700
@fontsource/ibm-plex-mono/400.css  500  600
```

No runtime Google Fonts request; the build is self-contained (`main.tsx:4-7`).

| Role | Stack | Source |
|---|---|---|
| Body / UI | `'IBM Plex Sans', system-ui, -apple-system, sans-serif` | `index.css:60` |
| Mono | `'IBM Plex Mono', ui-monospace, monospace` | `index.css:116-118` (`.mono`) |

**Base** — `font-size: 14px`, `line-height: 1.5`, `-webkit-font-smoothing: antialiased`
(`index.css:63-65`).

**Headings** — `h1..h4` share `font-weight: 600` and `letter-spacing: -0.01em`, margin 0
(`index.css:71-78`).

**Observed size scale** (ver2 sets sizes per component rather than declaring a named scale;
these are the values in use):

| px | Where | Source |
|---|---|---|
| 22 | page title `h1` | `index.css:367-369` |
| 14.5 | card header `h3` | `:461-463` |
| 14 | body base | `:63` |
| 13.5 | page subtitle; nav item | `:370-375`, `:180-188` |
| 13 | button; input; breadcrumb | `:384-397`, `:914-925`, `:256` |
| 12.5 | field label | `:859-864` |
| 12 | small button; textarea mono | `:417-420`, `:926-930` |
| 11.5 | badge; field hint | `:537-547`, `:865-870` |
| 11 | table header; nav count; xs button | `:655-665`, `:214-222`, `:437-441` |
| 10.5 | nav group label | `:173-179` |
| 10 | brand tag | `:160-169` |

**Weights** in use: 400 body, 500 buttons/labels/badges, 600 headings/table-headers/
`.pri-name`, 700 loaded but rare.

**Mono is semantic, not decorative.** Used for identifiers, counts and codes: nav counts
(`:214-222`), the brand tag (`:160-169`), `.tenantid` (`:293`), table `.id` cells (`:706`),
textarea input (`:926-930`).

---

## 2. Colour tokens

Declared twice and deliberately kept in sync — as CSS custom properties for hand-written CSS
(`index.css:17-49`) and as Tailwind theme tokens for utilities (`index.css:91-113`). Hex, not
oklch; ported verbatim from the V2 mockups (`index.css:18`).

### Ink (dark chrome — sidebar only)
| Token | Hex | Role | Source |
|---|---|---|---|
| `--ink` | `#0a0d14` | sidebar background | `:19`, `:92` |
| `--ink-2` | `#12161f` | nav hover / active background | `:20`, `:93` |
| `--ink-3` | `#1b212e` | nav count pill background | `:21`, `:94` |
| `--ink-line` | `#232b3a` | dividers on dark | `:22` |

### Brand
| Token | Hex | Role | Source |
|---|---|---|---|
| `--ion` | `#414bf5` | primary / accent / links / focus ring | `:23`, `:95` |
| `--ion-weak` | `#eaecfe` | info badge bg, selected table row | `:24`, `:96` |
| `--cyan` | `#19d3e0` | spectrum, brand tag, active-nav gradient | `:25`, `:97` |
| `--magenta` | `#e63dcb` | spectrum only | `:26`, `:98` |

Primary hover is `#333cdd` (`:407-408`) — a one-off, not a token.

### Surfaces and lines (light only)
| Token | Hex | Role | Source |
|---|---|---|---|
| `--canvas` | `#f6f7f9` | page background; clickable-row hover | `:27`, `:99` |
| `--surface` | `#ffffff` | cards, topbar, inputs, buttons | `:28`, `:100` |
| `--surface-2` | `#fbfcfd` | table header, zebra rows, button hover | `:29`, `:101` |
| `--line` | `#e5e9ef` | default border | `:30`, `:102` |
| `--line-2` | `#eef1f5` | subtle divider; ghost-button hover | `:31`, `:103` |

### Text hierarchy
| Token | Hex | Role | Source |
|---|---|---|---|
| `--text` | `#171c24` | primary | `:32`, `:104` |
| `--text-2` | `#586071` | secondary / subtitles | `:33`, `:105` |
| `--text-3` | `#8a93a3` | tertiary / table headers / hints | `:34`, `:106` |

### Status — each is a triple (fg / bg / line)
| Role | fg | bg | line | Source |
|---|---|---|---|---|
| ok | `#0e9b84` | `#e6f5f1` | `#bee6dd` | `:35-37` |
| warn | `#b26b00` | `#fbf1e3` | `#f0dbb8` | `:38-40` |
| fail | `#d0384a` | `#fbebed` | `#f2c9ce` | `:41-43` |
| info | `--ion` | `--ion-weak` | `#d3d7fb` | `:563-567` |
| live | `#0796a3` | `#e2f8fa` | `#b7ecf0` | `:568-572` |
| muted | `--text-2` | `--line-2` | `--line` | `:573-577` |

**The triple is the pattern.** A status colour is never used alone; every badge sets
foreground, background and border together.

### Light/dark handling
**ver2 is LIGHT-ONLY.** There is no `.dark` block, no `prefers-color-scheme` query and no
theme toggle anywhere in `index.css`. The dark ink tokens are chrome for the sidebar, not a
dark theme. This is the single largest divergence from CM — see §9.

---

## 3. Spacing and layout

**Shell** — a two-column grid, `index.css:121-125`:
```
.app { display: grid; grid-template-columns: 248px 1fr; min-height: 100vh; }
```
Sidebar is **248px**, sticky, full height, own scroll (`:126-135`).

**Topbar** — sticky, `z-index: 20`, white on a `--line` bottom border (`:239-245`), with a
3px spectrum strip above it: `linear-gradient(90deg, var(--cyan), var(--ion), var(--magenta))`
(`:246-249`). Bar padding `12px 26px`, gap 14 (`:250-255`).

**Content** — `padding: 24px 26px 90px`, **`max-width: 1240px`** (`:356-360`). The large
bottom padding is deliberate breathing room.

**Page head** — flex, gap 16, `margin-bottom: 18px`; `h1` 22px; subtitle `--text-2` 13.5px
with `max-width: 720px`; actions pushed right with `margin-left: auto`, gap 9
(`:361-383`).

**Observed spacing rhythm** — 2, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 24, 26. Not a strict
4/8 grid; component padding is tuned per component (buttons `8px 14px`, cards `14px 16px`
header / `16px` body, table cells `12px 14px`).

---

## 4. Shape and depth

| Token | Value | Source |
|---|---|---|
| `--r` / `--radius-dis` | `10px` | `:44`, `:110` |
| `--r-sm` / `--radius-dis-sm` | `7px` | `:45`, `:111` |
| `--r-lg` / `--radius-dis-lg` | `14px` | `:46`, `:112` |
| `--shadow` | `0 1px 2px rgba(16,24,40,.05), 0 1px 3px rgba(16,24,40,.04)` | `:47` |
| `--shadow-lg` | `0 10px 30px rgba(16,24,40,.12)` | `:48` |

Component radii that do **not** use the tokens (values as written): buttons and inputs `9px`
(`:388`, `:919`), nav items `8px` (`:185`), badges and nav counts `20px` (pill)
(`:544`, `:220`), focus-visible `4px` (`:82`), dots `50%` (`:580`).

**Depth is minimal.** `--shadow` appears on `.card` (`:452`). `--shadow-lg` is declared and
used sparingly. Borders, not shadows, do the separating work.

---

## 5. Component recipes

### Buttons — `index.css:384-447`
Base: inline-flex, gap 7, radius 9px, padding `8px 14px`, 13px/500, `1px solid --line`,
`--surface` bg, `--text` fg, `white-space: nowrap`. Hover → `--surface-2`.

| Variant | Recipe | Source |
|---|---|---|
| `.pri` | bg+border `--ion`, `#fff` text; hover `#333cdd` | `:401-408` |
| `.ghost` | transparent border+bg, `--text-2`; hover bg `--line-2` | `:409-416` |
| `.sm` | padding `5px 10px`, 12px | `:417-420` |
| `.xs` | padding `2px 7px`, 11px, line-height 1.4 | `:437-441` |
| `.danger` | `--fail` text, `--fail-line` border | `:442-446` |

**No disabled variant is defined in CSS.**

### Cards — `:448-471`
`--surface` bg, `1px solid --line`, `border-radius: var(--r)` (10px), `--shadow`.
Header `.hd`: flex, gap 10, padding `14px 16px`, bottom border `--line-2`, `h3` 14.5px,
actions right via `margin-left:auto` gap 8. Body `.bd`: padding 16.

### Badges — `:537-577`
Base: inline-flex, gap 6, 11.5px/500, padding `2px 9px`, `border-radius: 20px`,
`1px solid transparent`, nowrap. Then one of `.b-ok/.b-warn/.b-fail/.b-info/.b-live/.b-mut`,
each setting the fg/bg/line triple from §2.

**Dots** `:578-596` — 7×7, `border-radius: 50%`, `.d-ok/.d-warn/.d-fail/.d-mut`
(`--d-mut` is `#b4bcc9`, a one-off).

### Tables — `:655-732`
- `th`: left, 11px/600, `letter-spacing:.06em`, **uppercase**, `--text-3`, padding `10px 14px`,
  bottom `1px solid --line`, bg `--surface-2` (`:655-665`)
- `td`: padding `12px 14px`, bottom `1px solid --line`, middle-aligned (`:666-671`)
- last row: no bottom border (`:672-674`)
- **zebra**: `tbody tr:nth-child(even) td { background: --surface-2 }` (`:678-680`)
- **selected**: `tr[aria-selected='true'] td { background: --ion-weak }`, placed after zebra to
  win the specificity tie (`:684-686`)
- **hover on clickable rows only**: `tr.click:hover td { background: --canvas; cursor:pointer }`
  — never a false-interactive highlight on a static row (`:690-694`)
- `.pri-name` 600/`--text`; `.id` mono (`:692`, `:706`)

### Inputs — `:856-930`
`.field` mb 14; `label` block 12.5px/500 mb 6; `.hint` 11.5px `--text-3` mt 5.
`.input`, `select.input`, `textarea.input`: full width, `1px solid --line`, radius 9px,
padding `9px 12px`, `font: inherit`, 13px, `--surface` bg, `--text` fg.
`textarea.input`: min-height 78, **IBM Plex Mono 12px**.

### Nav — `:170-233`
Group label `.navgrp .lbl` 10.5px, `letter-spacing:.14em`. Items: flex, gap 10,
padding `8px 12px`, radius 8px, `#c4cbd8`, 13.5px; icon 15×15 at `opacity:.8`.
Hover **and** active share `background: --ink-2; color: #fff`. Active adds a 3px left rail:
`::before` with `linear-gradient(var(--cyan), var(--ion))`, inset 6px top/bottom, radius 3
(`:200-213`). Count chip `.ct`: mono 11px, `--ink-3` bg, radius 20, right-aligned.

### Chrome — sidebar and topbar `:121-255`  *(ADOPTED, chrome-alignment phase)*

**Shell** — `.app { display: grid; grid-template-columns: 248px 1fr; min-height: 100vh }` (`:121-125`).

**Sidebar** `.side` (`:126-135`) — `--ink` background, `#c4cbd8` text, flex column, sticky,
`100vh`, own scroll. Group label `.navgrp .lbl` (`:173-179`): 10.5px, `.14em`, uppercase,
**`#5a6474`**. Item `.nav a` (`:180-189`): gap 10, `8px 12px`, radius 8, `#c4cbd8`, 13.5px,
`position: relative`. Icon `.ico` 15×15 at `opacity .8` (`:190-195`).

**Hover and active are the SAME treatment** (`:196-205`) — `--ink-2` background, `#fff` text.

**Active rail** (`:206-213`) — `::before`, `left 0`, `top/bottom 6px`, `width 3px`, `radius 3`,
`linear-gradient(var(--cyan), var(--ion))`. **Two stops, VERTICAL.** This is not the topbar
spectrum and the two must not be conflated.

**Topbar** `.topbar` (`:239-245`) — sticky, `z-index 20`, **solid `--surface`**, bottom
`1px --line`. Bar `12px 26px`, gap 14 (`:250-255`).

**Spectrum** `.topbar .spectrum` (`:246-249`) — a 3px CHILD div above the bar, not a border:
`linear-gradient(90deg, var(--cyan), var(--ion), var(--magenta))`. **Three stops, HORIZONTAL.**
Mounted at `Shell.tsx:189-191`; it spans the topbar, which is a grid sibling of the sidebar, so
the strip covers the content column only.

**SOLID CHROME, NO TRANSLUCENCY — an adopted convention.** ver2's topbar is opaque `--surface`.
CM previously used `bg-background/95` with `backdrop-blur`; that was dropped. A blurred bar reads
as a different material from a solid one, and material inconsistency is one of the loudest ways
two apps look unrelated.

### Boxes — `.note` `:811`, `.warnbox` `:819`, `.failbox` `:827`, `.okbox` `:835`, `.empty` `:843`
Inline message surfaces using the same status triples.

---

## 6. Interaction states

| State | Convention | Source |
|---|---|---|
| Focus | **Global**: `:focus-visible { outline: 2px solid var(--ion); outline-offset: 2px; border-radius: 4px }` | `:79-83` |
| Hover (button) | → `--surface-2`; primary → `#333cdd`; ghost → `--line-2` | `:398-400`, `:407`, `:414` |
| Hover (nav) | → `--ink-2` bg, `#fff` text | `:196-199` |
| Hover (row) | **only** on `tr.click` → `--canvas` + pointer | `:690-694` |
| Active/selected | nav: `--ink-2` + gradient rail; row: `--ion-weak` | `:200-213`, `:684-686` |
| Disabled | **not defined in CSS** — see §9 | — |

Focus is one global rule rather than per-component ring utilities. This is the single most
portable thing in the system and CM should adopt it wholesale.

---

## 7. What ver2 does NOT have

Confirmed absent by grep over `src/index.css` (`modal|dialog|toast|snackbar|overlay|backdrop`
→ **zero matches**):

- **No modal / dialog / overlay**
- **No toast / snackbar**
- **No dark mode**
- **No disabled-state recipe**
- **No skeleton/shimmer, no animation tokens** (no duration or easing custom properties)
- **No tooltip recipe**

CM has all six. Treatments derived from ver2 tokens are proposed in the gate report; none is
sourced from the older DIS UI.

---

## 8. Porting notes for a Next.js consumer

**Fonts.** ver2 imports `@fontsource/*` CSS in `main.tsx`. CM uses `next/font/google`
(`app/layout.tsx:2-16`, Geist + Geist Mono). Two options, both legitimate:
add `@fontsource/ibm-plex-sans|mono` and import in `app/layout.tsx`, or switch the existing
`next/font/google` calls to `IBM_Plex_Sans`/`IBM_Plex_Mono`. The second keeps Next's
self-hosting, preload and CLS handling and changes fewer lines — but it is a *mechanism*
difference from ver2, which is why it is recorded here rather than assumed.

**Tokens.** Both apps are Tailwind v4 CSS-first, so ver2's `@theme` block ports almost
verbatim. CM's `@theme inline` indirects through `:root` custom properties
(`app/globals.css`), which is the better shape to keep: map CM's semantic names onto ver2's
values rather than renaming call sites.

**Colour space.** ver2 is hex; CM is oklch. Hex is authoritative here — ver2's own comment
says the values are ported verbatim from the mockups and must not be converted
(`index.css:18`).

---

## 9. DERIVED — not present in ver2

Everything in this section is a Customer Master addition. **None of it is sourced from
`dis/services/dis-ui`**; each is built from ver2's own tokens and is recorded here so the
divergence is visible rather than discovered.

### 9.1 Dark mode

ver2 is light-only — no `.dark`, no `prefers-color-scheme`, no toggle. CM ships a three-way
theme control (`next-themes` in `app/providers.tsx`, the switch in
`components/chrome/UserMenu.tsx`), so removing dark mode would delete a working feature.
The dark palette is therefore derived, and **only from ver2's ink family**, which ver2 uses
for its sidebar chrome.

| ver2 token | hex | Source | CM dark role |
|---|---|---|---|
| `--ink` | `#0a0d14` | `index.css:19` | `--background` |
| `--ink-2` | `#12161f` | `:20` | `--surface`, `--card`, `--sidebar` |
| `--ink-3` | `#1b212e` | `:21` | `--surface-raised`, `--secondary`, `--muted`, `--accent`, `--popover` |
| `--ink-line` | `#232b3a` | `:22` | `--border`, `--input`, `--sidebar-border` |

Text on dark uses ver2's own sidebar values — `#c4cbd8` (`index.css:128`, nav resting) for
`--foreground-muted`, `#ffffff` (`:198`, nav active) for `--foreground`, and `--text-3`
`#8a93a3` for `--foreground-subtle`.

**Status and accent hex are ver2-verbatim in BOTH modes**, by decision: a `danger` that shifted
between themes would be two different reds. Only the status *backgrounds* and *lines* change on
dark — ver2's pale `#fbebed`-family fills are unreadable on `#0a0d14`, so they resolve to the
ink surfaces instead.

### 9.2 The sidebar on dark

ver2's sidebar is `--ink` `#0a0d14` and ver2 has no dark mode. On CM's dark theme the PAGE is
already `--ink`, so a sidebar at `--ink` would vanish into it.

**The rail moves one step up the same ladder instead:**

| | page | sidebar | hover/active |
|---|---|---|---|
| light | `--canvas` `#f6f7f9` | `--ink` `#0a0d14` | `--ink-2` `#12161f` |
| dark | `--ink` `#0a0d14` | `--ink-2` `#12161f` | `--ink-3` `#1b212e` |

So the sidebar is the **darkest surface on light** and **one step lighter than the page on
dark**. The relationship inverts; the legibility does not. Every value is from ver2's ink
family — no new hex — and `--sidebar-border` `--ink-line` `#232b3a` keeps a crisp edge in both.

`--sidebar-muted` `#5a6474` is ver2's group-label colour (`index.css:176`), promoted to a token
because CM's sidebar previously used `--muted-foreground`, which is a light-theme value and is
unreadable on the dark rail.

**THE ACTIVE RAIL IS KEPT WHEN COLLAPSED.** ver2 has no collapsed state, so there is nothing to
be faithful to; the choice is CM's. It stays because at `w-16` the labels are gone and the rail
is the only thing distinguishing active from hover — the background fill alone reads as hover at
icon size. It matters more collapsed, not less.

### 9.3 Tones ver2 has no palette for

`Chip` carries `violet` and `purple` for org-node categories; ver2 has no categorical hues.
Derived from its spectrum accents — `--magenta` `#e63dcb` (`index.css:26`) and `--cyan`
`#19d3e0` (`:25`) — via `color-mix`, distinguished by fill weight. Same for
`OrgNodeTypeBadge`, `OrgNodeTypeIcon`, `ModuleSummaryCard` and `KpiCard`.

### 9.4 Patterns ver2 lacks entirely

Confirmed absent (`modal|dialog|toast|snackbar|overlay|backdrop` → zero matches in
`index.css`). Treatments, all ver2-token-derived. **Status column added when these were
applied** — declaring a treatment and shipping it are different things, and the gap between
them lasted two phases.

| Pattern | Treatment | Status |
|---|---|---|
| Modal / dialog | `--surface`, `--radius-lg` (14px), `--shadow-md-value`; backdrop `--ink` at 55% | **APPLIED** — `ui/dialog.tsx`, `ui/alert-dialog.tsx`, `ui/sheet.tsx` |
| Toast (Sonner) | card recipe at `--radius-md`, `--shadow-md-value`, status triples per variant | **APPLIED** — `ui/sonner.tsx`, `.cn-toast` |
| Tooltip | `--ink-2` bg, `#fff` text, `--radius-sm` | **DECLARED, NOT APPLIED** — see below |
| Disabled | `opacity: .55` + `cursor: not-allowed`; no token change | **APPLIED** (partial — see below) |
| Skeleton | `--surface` base, `--surface-raised` sweep | **ALREADY CORRECT** — `skeleton-shimmer` |
| Animation | ver2 has no duration/easing tokens — CM's existing scale is kept | n/a |

**`--ink` IS NOW A LIVE TOKEN.** It previously existed only as a value baked into
`--background` (dark) and `--sidebar`. The backdrop needs it by name, and it is declared in
`:root` and deliberately **not** overridden in `.dark`: a scrim is not a themed surface, so 55%
ink is one value in both modes.

**Tooltips: declared, not applied, on purpose.** CM has no tooltip *component* in use — hints
are native `title` attributes, which cannot be styled. Introducing a component to carry this
recipe would add hover/focus/dismiss behaviour where there is none today, which is a behaviour
change, not a restyle. ver2 has no tooltip either, so there is no anchor to derive one from.
The recipe above stands ready for the first real tooltip component; until then `ui/tooltip.tsx`
keeps its own styling and is used only where a component already existed.

**One colour authority for toasts.** Sonner ships `richColors`, a built-in status palette. It is
**not enabled and must not be**: it would be a third set of status colours beside ver2's tokens
and the Chip triples, and the one nobody updates when the palette moves. Every variant binds to
the same `--success`/`--warning`/`--danger` triples the badges use.

**Disabled is partial, and the reason is not laziness.** `disabled:opacity-55` is applied
everywhere (verified generated: `opacity:.55` is in the built CSS). `cursor: not-allowed` is
**not** added where `disabled:pointer-events-none` already sits — pointer-events-none suppresses
the cursor entirely, so the two together are contradictory and the cursor rule would be inert.

### 9.5 `--border-strong`

CM hovers by strengthening a border; ver2 hovers by shifting a **background** and has only two
line tokens (`--line` `#e5e9ef`, `--line-2` `#eef1f5`, the latter *lighter*). Mapped to
`--text-3` `#8a93a3` — a real ver2 value and the nearest thing stronger than `--line`. The
faithful long-term fix is to migrate CM's hover recipes to background-shift, which is what ver2
actually does.

---

## 10. Semantic alias table

CM's token names are kept so no call site changes; only the values move to ver2.

| CM token | ver2 token | hex | Note |
|---|---|---|---|
| `--background` | `--canvas` | `#f6f7f9` | |
| `--foreground` | `--text` | `#171c24` | |
| `--foreground-muted` | `--text-2` | `#586071` | |
| `--foreground-subtle` | `--text-3` | `#8a93a3` | |
| `--surface`, `--card`, `--popover` | `--surface` | `#ffffff` | ver2 has one surface |
| `--surface-raised`, `--secondary` | `--surface-2` | `#fbfcfd` | |
| `--muted` | `--line-2` | `#eef1f5` | |
| `--accent` | `--ion-weak` | `#eaecfe` | |
| `--accent-foreground` | `--ion` | `#414bf5` | |
| `--primary`, `--ring`, `--info` | `--ion` | `#414bf5` | ver2's info badge IS ion (`:563`) |
| `--success` | `--ok` | `#0e9b84` | + `-bg` `#e6f5f1`, `-line` `#bee6dd` |
| `--warning` | `--warn` | `#b26b00` | + `-bg` `#fbf1e3`, `-line` `#f0dbb8` |
| `--danger`, `--destructive` | `--fail` | `#d0384a` | + `-bg` `#fbebed`, `-line` `#f2c9ce` |
| `--border`, `--input` | `--line` | `#e5e9ef` | |
| `--border-strong` | `--text-3` | `#8a93a3` | **derived**, §9.4 |
| `--sidebar*` | `--ink` ladder | `#0a0d14` | ver2's always-dark rail; dark derivation § 9.2 |
| `--sidebar-muted` | `.navgrp .lbl` | `#5a6474` | index.css:176 |
| `--radius-sm` | `--r-sm` | `7px` | |
| `--radius` | (buttons/inputs `:388`) | `9px` | |
| `--radius-md` | `--r` | `10px` | |
| `--radius-lg`, `--radius-xl` | `--r-lg` | `14px` | ver2 has nothing larger |

---

## 11. Closed

Nothing is parked. The section stays rather than being deleted: a spec that silently loses its
parked list reads as though nothing was ever parked.

**The 1240px content cap — ADOPTED.** `app/(authenticated)/layout.tsx` now wraps every route in
one container, matching ver2's `.content` (`index.css:356-360`: `max-width: 1240px`,
`padding: 24px 26px 90px`), which `Shell.tsx:233` applies to every route in ver2.

**The reconciliation this was parked on.** The premise was "ver2's 1240 vs Synapse's 840" — two
systems. The audit found THREE, and ver2's 1240 was not among them: the chrome-alignment phase
ported ver2's colour and chrome but never its container, so cm-frontend had

  - unbounded pages (users, tenants, stores, audit, roles, modules, org, dashboard, onboard),
  - an 840px LEFT-ALIGNED column on the Synapse pages and atlas (`Column`, no `mx-auto` — so it
    was never the centred reading column the name implied), and
  - assorted centred caps outside superadmin (my-ithina 1024, profile 768).

**Why everything went wide rather than a two-tier system.** ver2 has exactly one container and
no page-type variation — a grep for per-page `maxWidth` in its components returns nothing. The
only narrowing anywhere in ver2 is `.pagehead .sub { max-width: 720px }` (`index.css:374`), which
caps subtitle PROSE. So ver2's answer to "do reading-heavy views narrow?" is: the page does not,
the prose does. A two-tier page system would have been an invention attributed to ver2.

**The reading measure.** ver2's number and mechanism, as the `text-measure` utility
(`app/globals.css`): `max-width: 720px`, applied to sentences rather than pages. It replaced
Tailwind's `max-w-prose` (65ch) everywhere — two measures for one job is how a design system
stops being one, and 720px is the one with a citation behind it.

Applied to: `Footnote`, `Attention`'s detail, `SynapseDown`'s message, the alert detail page's
"why it was flagged" sentence, and the explanatory copy on capabilities and analyses. NOT applied
to tables, run history, monitor lists, stat grids or product cards — those take the full
container.

**`Column` survives as a SPACING primitive.** It keeps `px-6` (which aligns the body's left edge
with `PageHeader`'s own `px-6`) and the vertical rhythm; the width bound is gone. A second cap
inside a correct container would have left the Synapse pages the odd ones out again.

The sidebar and topbar spectrum that used to sit here were adopted in the chrome-alignment
phase; their recipes are in §5 and the dark-mode derivation is §9.2.
