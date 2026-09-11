// Shared markup for the Synapse superadmin screens. Server-safe: no hooks, no
// "use client" — every Synapse page is a server component so the BFF stays
// unreachable from the browser.
//
// Uses the shared typography scale (text-display / text-body /
// text-caption / text-label / text-micro), semantic colour tokens
// (text-foreground-muted, bg-surface, border-border) rather than ad-hoc
// zinc/slate/gray, and rounded-md for cards.

import type { ReactNode } from "react";

import { Chip, type Tone as ChipTone } from "@/components/shared/Chips";

// ---------------------------------------------------------------------------
// THE BOUNDED READING COLUMN — the fix that makes the rest legible
// ---------------------------------------------------------------------------
//
// The app fills the window; the content does not. Without a bound every screen ran
// edge to edge on a 1900px monitor and a label sat half a screen from its value,
// which is a proximity failure no amount of correct colour can rescue.
//
// THE BOUND MOVED OUT OF HERE. This used to carry `max-w-[840px]`, left-aligned,
// chosen before ver2's system arrived — measured against a mockup rather than
// derived from anything, as the comment that used to sit here admitted ("two
// precedents exist in this repo and they disagree"). ver2 has ONE container at
// 1240px (index.css:356-360) applied to every route by its Shell, and NO page type
// narrows below it. cm-frontend now has the same container in
// app/(authenticated)/layout.tsx, so a second cap here would be a narrower box
// inside a correct one, and the Synapse pages would stay the odd ones out.
//
// WHAT NARROWS INSTEAD IS PROSE, which is also ver2's answer: `.pagehead .sub` is
// capped at 720px (index.css:374) and nothing else is. That is the `text-measure`
// utility, applied to sentences rather than to pages.
//
// SO THIS IS NOW A SPACING PRIMITIVE, not a width one. It keeps px-6 — which is
// what lines the body's left edge up with PageHeader's own px-6 — and the vertical
// rhythm. The six Synapse screens had no horizontal padding at all before it
// existed: PageHeader was inset and the body was flush to the sidebar, so a page
// did not align with its own title.
//
// =========================================================================================
// THE FOUR-LAYER SEAM ABOVE THIS COMPONENT, ACCEPTED IN B2 RATHER THAN UNNOTICED
// =========================================================================================
// Everything below this line sits on the page background with white cards on it, which is
// what the mockups draw. What sits ABOVE it does not match them, and the divergence is
// deliberate:
//
//     white sticky TopBar  ->  white PageHeader band  ->  grey page  ->  white cards
//
// The mockups have no header band at all. Their h1 sits INSIDE the content area directly on
// the page background at 20px, so a reader meets one white-on-grey boundary; here they meet
// three, and the 14px card radius makes the last one slightly more visible than 10px did.
// PageHeader also renders text-display at 24px against the mockups' 20px.
//
// NEITHER IS FIXED HERE AND BOTH WERE CONSIDERED. PageHeader is shared with every screen in
// cm-frontend, so restyling it would leave Synapse and restyle Governance, Access Control
// and the rest, which is exactly what this slice was scoped not to do. Moving the Synapse
// pages off it is an IA change, and B2b-1 settled the IA. So the seam stays, recorded, and
// whoever revisits it is changing a shared component on purpose rather than discovering a
// mismatch nobody had looked at.
export function Column({ children }: { children: ReactNode }) {
  return (
    <div className="px-6 pt-6">
      <div className="space-y-6">{children}</div>
    </div>
  );
}

// StatStrip AND Stat WERE HERE AND ARE DELETED (B3). They were the inline strip: a
// `text-heading` figure over a caption, laid straight on the page background. Both are
// REPLACED BY StatCards AND StatCard below, which is the mockups' own treatment for stats and
// is now used on all three stat surfaces (the fleet overview, the tenant Overview tab and the
// alert detail page).
//
// THE ARGUMENT THEY SHIPPED WITH IS WORTH KEEPING, because it is still true of the thing that
// replaced them: stats are CONTEXT rather than the point of a page, and a screen where four
// figures are all emphasised has emphasised nothing. StatCard carries that by giving only the
// figure that means something the `warn` colour, not by being quiet everywhere.

// ---------------------------------------------------------------------------
// Two facts, two columns
// ---------------------------------------------------------------------------
//
// Label left, value right, MONOSPACE on the value so dates align down the column
// and a reader can compare them without reading each one. The prose that used to
// be a third column is a footnote now: see Footnote.
// AUTO LAYOUT, NOT `table-fixed`, and the difference is the whole point of the
// change. Fixed layout splits two columns 50/50, which at 840px puts the label's
// end around x=200 and the value's start around x=600 — the same proximity
// failure the bounded column exists to fix, reproduced at smaller scale. Auto
// layout sizes the label column to its content and pulls the value in beside it.
// Checked against the mockup rather than assumed: its `.facts` sets
// `border-collapse:collapse` and no `table-layout`.
export function Facts({ children }: { children: ReactNode }) {
  return (
    <table className="w-full">
      <tbody>{children}</tbody>
    </table>
  );
}

export function Fact({
  label,
  value,
  note,
}: {
  label: string;
  value: ReactNode;
  note?: string;
}) {
  return (
    <tr className="border-b border-border align-baseline last:border-b-0">
      <td className="text-body py-3 pr-4 text-foreground-muted">{label}</td>
      <td className="py-3 pl-4 text-right whitespace-nowrap">
        <span className="text-body font-mono text-foreground">{value}</span>
        {note ? (
          <span className="text-caption ml-2 font-normal text-foreground-subtle">{note}</span>
        ) : null}
      </td>
    </tr>
  );
}

// Row WAS HERE AND IS DELETED (B3). It was the pre-restyle list primitive: a ruled row laid
// straight on the page background, with a title, a metadata line, a right-hand slot and an
// `attention` flag that turned the title amber.
//
// EVERY CALL SITE MOVED IN B2 AND NOTHING REPLACED IT ONE FOR ONE, which is why it went from
// eleven uses to zero without anyone noticing. The four treatments each took a share: alert
// lists became PanelRow inside a Panel, the fleet roster became Tr inside a TableCard, the
// tenant monitors became ItemCard, and the capabilities list became a TableCard too. The
// `attention` amber survives as the same two classes applied at the two alert list sites.
//
// A DEAD EXPORT IS THE SAME CLASS OF ARTIFACT AS A FALSE COMMENT: it tells the next reader this
// is how a list is built here, and it is not. Recorded rather than silently removed, the same
// way NameWithId and Unavailable are recorded below.

// ---------------------------------------------------------------------------
// The footnote: teaching copy, once, quieter than the data
// ---------------------------------------------------------------------------
//
// The idempotency sentence appeared on two consecutive rows. An explanation is
// worth reading once and is clutter every time after — so it sits under the
// section it explains, at caption weight, where a returning reader skips it.
// text-measure rather than a hand-picked character count: it is the house token,
// already used nine times, and it replaces the three different ch values the
// mockup reached for.
export function Footnote({ children }: { children: ReactNode }) {
  return <p className="text-caption text-measure text-foreground-subtle">{children}</p>;
}

// The amber banner for the thing that needs a person. NOT a row that looks like
// the others — that was the R1 failure: the one item requiring action was styled
// identically to the three that did not.
//
// =========================================================================================
// A BANNER IS NOT A CARD, AND THIS RADIUS IS 9px ON PURPOSE. DO NOT RAISE IT TO rounded-lg.
// =========================================================================================
// B2 raised both banners here to the 14px card radius on the reasoning that they are
// card-level objects. That reasoning is wrong and the mockups settle it: the only banner
// they draw is mockup-overview's `.banner`, and it is `border-radius: var(--r-md)`, which is
// 9px, the same step as a filter control. The 14px slot is for the four content treatments
// (Panel, TableCard, ItemCard, StatCard); a banner is a notice laid over the page, not one of
// the objects the page is built from. Corrected in B3 by whoever raised it.
export function Attention({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="rounded border border-[var(--warning-line)] bg-[var(--warning-bg)] p-4">
      <p className="text-body-strong text-warning">{title}</p>
      <p className="text-caption mt-1 text-measure text-warning/80">
        {detail}
      </p>
    </div>
  );
}

// R2 had no way back. "My Sevyn8" was the only upward link in the chrome and it
// goes somewhere else entirely, so a tenant panel was a dead end.
// `tenantHref` turns the client name into a LINK rather than the last crumb, which
// is what a third level needs. Omitted on the tenant page itself: a crumb pointing
// at the page you are on is a dead control, and the current page is never a link.
export function Breadcrumb({
  tenant,
  tenantHref,
  current,
}: {
  tenant: string;
  tenantHref?: string;
  current?: string;
}) {
  return (
    <nav className="text-caption text-foreground-muted" aria-label="Breadcrumb">
      <a className="text-primary underline-offset-2 hover:underline" href="/superadmin/synapse">
        Synapse
      </a>
      {" · "}
      <a className="text-primary underline-offset-2 hover:underline" href="/superadmin/synapse">
        Fleet
      </a>
      {" · "}
      {tenantHref ? (
        <a className="text-primary underline-offset-2 hover:underline" href={tenantHref}>
          {tenant}
        </a>
      ) : (
        <span className="text-foreground">{tenant}</span>
      )}
      {current ? (
        <>
          {" · "}
          <span className="text-foreground">{current}</span>
        </>
      ) : null}
    </nav>
  );
}

// ---------------------------------------------------------------------------
// SECTION NAVIGATION: the mockups' left rail, as a strip inside the section
// ---------------------------------------------------------------------------
//
// THE MOCKUPS' RAIL IS NOT THIS APP'S SIDEBAR. Each mockup draws a dark rail
// listing Overview / Monitors / Alerts / Tenants / Runs and then Capabilities /
// Analyses, because each mockup is a standalone Synapse app whose entire
// navigation that rail is. cm-frontend already has a product-wide sidebar with
// five groups, of which Synapse is ONE ENTRY under Modules. Copying the rail
// into it would make Synapse's surfaces permanently as prominent as the whole of
// Governance, from every page in the product, so the rail maps to SECTION
// navigation instead.
//
// PASSES `current` RATHER THAN READING THE PATH. usePathname would make this a
// client component, and this file is server-safe on purpose: every Synapse page
// is a server component so the BFF stays unreachable from a browser. Each page
// naming itself is also how Breadcrumb already works here.
//
// SIX ENTRIES, NOT EIGHT, AND BOTH ABSENCES ARE DELIBERATE. "Monitors" would
// point at a catalog page that does not exist yet, and "Tenants" at a roster
// that lives on Overview. A nav entry pointing at nothing is a dead control, and
// two entries pointing at one page is worse than six honest ones. Both arrive
// with their pages.
//
// "Deliveries" IS THE SIXTH AND IT IS AXON'S, NOT SYNAPSE'S, which is why it sits
// in the Platform group beside Capabilities and Analyses. Axon is a PEER of
// Synapse rather than part of it: it carries the platform's outbound
// communications, and Synapse's enable route is only its first producer. Putting
// it under the Synapse heading would say the delivery ledger belongs to the
// monitoring plane, which is the misreading that would make somebody look for
// tenant messaging inside Synapse later.
//
// IT LIVES ON THIS STRIP AT ALL because the strip is the console's section rail
// and the ledger is a console surface. When Axon grows surfaces of its own (an
// address book, templates, a queue) they get their own rail and this entry moves
// to it. One entry does not justify a second rail.
export type SynapseSection =
  | "overview"
  | "alerts"
  | "runs"
  | "capabilities"
  | "analyses"
  | "deliveries";

const SECTIONS: ReadonlyArray<{ key: SynapseSection; label: string; href: string; group: string }> = [
  { key: "overview", label: "Overview", href: "/superadmin/synapse", group: "Synapse" },
  { key: "alerts", label: "Alerts", href: "/superadmin/synapse/alerts", group: "Synapse" },
  { key: "runs", label: "Runs", href: "/superadmin/synapse/runs", group: "Synapse" },
  {
    key: "capabilities",
    label: "Capabilities",
    href: "/superadmin/synapse/capabilities",
    group: "Platform",
  },
  { key: "analyses", label: "Analyses", href: "/superadmin/synapse/analyses", group: "Platform" },
  {
    key: "deliveries",
    label: "Deliveries",
    href: "/superadmin/axon/deliveries",
    group: "Platform",
  },
];

export function SubNav({ current }: { current: SynapseSection }) {
  return (
    <nav aria-label="Synapse sections" className="flex flex-wrap items-center gap-x-1 gap-y-2">
      {SECTIONS.map((section, index) => {
        // The mockups' rail splits Synapse from Platform with a group label. A
        // horizontal strip has no room for two headings, so the boundary is a
        // rule: the same information, in the space available.
        //
        // READS THE PREVIOUS ENTRY BY INDEX rather than carrying a running
        // variable. SECTIONS is a module constant, so the comparison is pure;
        // a `let` reassigned inside the map is a mutation during render, which
        // React's immutability rule refuses and which would be wrong under any
        // future re-render or reordering.
        const boundary = index > 0 && SECTIONS[index - 1]!.group !== section.group;
        const active = section.key === current;
        return (
          <span key={section.key} className="flex items-center">
            {boundary ? (
              <span aria-hidden="true" className="mx-2 h-4 w-px shrink-0 bg-border" />
            ) : null}
            <a
              href={section.href}
              aria-current={active ? "page" : undefined}
              className={`text-caption rounded px-2.5 py-1.5 transition-colors duration-150 ease-out ${
                active
                  ? "bg-surface-raised text-foreground font-medium"
                  : "text-foreground-muted hover:bg-surface-raised hover:text-foreground"
              }`}
            >
              {section.label}
            </a>
          </span>
        );
      })}
    </nav>
  );
}

// ---------------------------------------------------------------------------
// TABS: one route, one fetch set, the tab in the query string
// ---------------------------------------------------------------------------
//
// PLAIN LINKS, NOT components/ui/tabs.tsx. That one is base-ui, client-side, with
// a sliding indicator and its own state machine; adopting it would turn the
// tenant page into a client island purely to switch sections, and the whole
// reason these pages are server components is that the BFF is not reachable from
// a browser. The state lives in the URL, which also makes a tab linkable and
// survives a refresh. Same argument the capabilities page made for <details>.
//
// COUNT IS OPTIONAL AND RENDERS ONLY WHEN GIVEN. A tab showing "0" where the
// number is simply unknown would be a claim; absence is not.
export function Tabs({
  tabs,
  current,
}: {
  tabs: ReadonlyArray<{ key: string; label: string; href: string; count?: number }>;
  current: string;
}) {
  return (
    <nav aria-label="Sections" className="flex flex-wrap gap-x-1 border-b border-border">
      {tabs.map((tab) => {
        const active = tab.key === current;
        return (
          <a
            key={tab.key}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={`text-body -mb-px border-b-2 px-3.5 py-2.5 transition-colors duration-150 ease-out ${
              active
                ? "border-primary text-foreground font-semibold"
                : "border-transparent text-foreground-muted hover:text-foreground"
            }`}
          >
            {tab.label}
            {tab.count !== undefined ? (
              <span className="text-micro ml-1.5 rounded-full bg-[var(--info-bg)] px-1.5 py-0.5 font-semibold tabular-nums text-info">
                {tab.count}
              </span>
            ) : null}
          </a>
        );
      })}
    </nav>
  );
}

export function SectionHead({ children }: { children: ReactNode }) {
  return (
    <h2 className="text-label mt-6 mb-3 border-b border-border pb-1.5 text-foreground-subtle first:mt-0">
      {children}
    </h2>
  );
}

// Three meanings, and the middle one is the point (D5).
//
//   good     a real finding: "1 found"
//   unknown  a "0" we CANNOT interpret — see below
//   mute     nothing, and we know it is nothing
//   stop     it failed
//
// WHY "unknown" EXISTS RATHER THAN A BARE 0. A run that proposed zero actions is
// either "looked and found no risk" or "found nothing — sales data too old".
// Rendering both as "0 found" would be a guess presented as a result; rendering
// both as "cannot assess" would be a different guess. The third state says
// exactly what is true: zero, and we cannot tell which.
//
// THE HEDGE WAS LATER NARROWED, not removed. The run row now carries a
// refusal breakdown, so a run that refused series SAYS SO and the screen
// names the reason. The hedge still applies where the breakdown is null —
// a run that never reached its plan, or one predating migration 0005 —
// which is exactly the case where the data genuinely cannot tell which.
export type Tone = "good" | "unknown" | "mute" | "stop";

// DELEGATES TO THE HOUSE CHIP rather than restating its recipe. Chips.tsx
// already resolves each tone through one set of semantic tokens shared by
// both themes; a second copy here would be a second source of truth for
// what a status chip looks like, and the copy that drifts is always the
// one nobody is looking at.
const TONE_TO_CHIP: Record<Tone, ChipTone> = {
  good: "green",
  unknown: "amber",
  mute: "grey",
  stop: "red",
};

// `dot` DEFAULTS TO FALSE HERE, AND B2 IS WHERE IT FLIPPED. B1 left it true so that opting out on
// the runs page changed nothing anywhere else; the sentence it shipped with said the rest of the
// console follows in Phase B2, and this is that. No mockup draws a dot on any pill: the tone
// already says what the dot repeats, and eight mockups agreeing is enough.
//
// THE DEFAULT MOVES HERE, NOT IN Chips.tsx. That file is the house chip used across Governance,
// Access Control and the rest, which this slice deliberately does not restyle. Flipping it there
// would restyle every chip in the product from a Synapse ticket. This wrapper is Synapse's, so
// the override lives in it, which is the same containment argument as the card radius below.
export function Tag({
  tone,
  children,
  dot = false,
}: {
  tone: Tone;
  children: ReactNode;
  dot?: boolean;
}) {
  return (
    <Chip tone={TONE_TO_CHIP[tone]} dot={dot}>
      {children}
    </Chip>
  );
}

// =================================================================================================
// THE CARD RADIUS: rounded-lg, AND THERE WAS NEVER A HOUSE-VERSUS-MOCKUP ARGUMENT TO HAVE
// =================================================================================================
// B1 ruled for rounded-md (10px) over the mockups' 14px, on the grounds that 135 call sites to 2
// made Synapse the odd one out. B2 overturns that ruling, and the reason is not a change of taste:
// THE PREMISE WAS WRONG.
//
// `--radius-lg` IS ALREADY 14px (globals.css:100), ported from dis-ui-ver2's own `--r-lg`
// (index.css:46) in the same commit that set --radius-md to 10px. The mockups' card radius is
// --r-xl: 14px. So the mockups were never asking for a value outside the house scale; they were
// asking for a DIFFERENT SLOT IN IT, and the card was pointed at the wrong existing token.
//
// The whole mockup radius vocabulary is already here, one for one:
//
//     mockup --r-sm  7px   =  --radius-sm  7px    MonoChip, filter chips     (already correct)
//     mockup --r-md  9px   =  --radius     9px    selects, buttons, groups   (`rounded`)
//     mockup --r-xl 14px   =  --radius-lg 14px    cards and panels           (this file)
//
// SO NOTHING SHARED MOVES. No token is added, no token is edited, and --radius-md keeps its 10px
// for the other 134 files that use it. The override is a class choice at Synapse call sites only,
// which is what "Synapse leads and the rest of the product does not follow" means in practice.
// DO NOT re-open this as 10 versus 14: the question was which token the card slot points at.
//
// ---------------------------------------------------------------------------
// THE PANEL: one of FOUR content treatments, not the only one
// ---------------------------------------------------------------------------
//
// A white surface on the page background, a hairline border, a raised header strip, ruled rows,
// and an optional quieter note along the bottom.
//
// THE MOCKUPS DO NOT USE THIS EVERYWHERE, and B2's audit turned on that. They carry FOUR content
// treatments and applying this one uniformly would be as wrong as applying none of it:
//
//   1. Panel with grouped rows   RUNS ONLY. One panel per slot, header strip, ruled rows.
//   2. Table in a card           the fleet roster and capabilities. See TableCard.
//   3. Rows in one card          the alerts inbox and the tenant alert list. This Panel with
//                                PanelRow children and no header, which is why that case needs
//                                no new component.
//   4. Card per item             tenant Monitors and analyses. See ItemCard.
//
// DARK MODE FLATTENS THE HEADER STRIP, and B2 spreads that from the runs page to every surface.
// In dark, --surface-raised and --muted are both #1b212e (globals.css:218, 227), so PanelHeader
// and PanelNote sit closer to their rows than the light theme's #fbfcfd against #ffffff. Known
// consequence of using the token rather than a hand-picked value, recorded here rather than
// discovered later. Not a defect: the hairline still separates them, and the fix would be a new
// dark surface step, which is a token decision for the whole product rather than for Synapse.
export function Panel({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">{children}</div>
  );
}

// The raised strip: a title, a summary, and a right-aligned meta rail. `items-baseline`
// rather than `items-center` so the mono date and the sentence beside it sit on one line
// of type instead of being centred against each other.
export function PanelHeader({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-border bg-surface-raised px-4 py-3">
      {children}
    </div>
  );
}

// One ruled row. `items-start` because a row's detail column can wrap to several lines and
// its name and status must stay pinned to the top rather than floating to the middle of it.
export function PanelRow({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start gap-x-4 gap-y-2 border-b border-border px-4 py-3 transition-colors duration-150 ease-out last:border-b-0 hover:bg-surface-raised">
      {children}
    </div>
  );
}

// The quiet line along the bottom of a panel: a caveat about the rows above it, styled so it
// reads as an annotation on the panel rather than as one more row of data.
export function PanelNote({ children }: { children: ReactNode }) {
  return (
    <p className="text-micro border-t border-border bg-surface-raised px-4 py-2.5 text-foreground-subtle">
      {children}
    </p>
  );
}

// ---------------------------------------------------------------------------
// TREATMENT 2: THE TABLE IN A CARD
// ---------------------------------------------------------------------------
//
// The fleet roster, the tenants list and capabilities are all ONE card containing a real table:
// an uppercase header strip on the raised surface, ruled body rows, and an optional note along
// the bottom. Columnar because the reader is comparing rows down a column, which is the thing a
// list of Row components cannot do however it is styled.
//
// A REAL <table>, not a grid of divs. These are tabular data with headers, so the semantics are
// free and a screen reader gets the column association it would otherwise lose.
//
// AUTO LAYOUT, NOT table-fixed. Same reason Facts above says so: fixed layout splits the columns
// evenly and pushes a short label away from its value, which is the proximity failure the bounded
// column exists to fix, reproduced one level down. The mockups set border-collapse and no
// table-layout, which is auto.
export function TableCard({
  head,
  children,
  foot,
}: {
  head: ReactNode;
  children: ReactNode;
  foot?: ReactNode;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">
      <table className="w-full border-collapse">
        <thead>
          <tr>{head}</tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
      {foot ? <PanelNote>{foot}</PanelNote> : null}
    </div>
  );
}

// The uppercase column label. text-label IS the mockups' rule (11px, .08em, uppercase, weight
// 500) at the house size, so nothing here is hand-tuned.
export function Th({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <th
      scope="col"
      className={`text-label border-b border-border bg-surface-raised px-4 py-3 text-left align-bottom text-foreground-subtle ${className ?? ""}`}
    >
      {children}
    </th>
  );
}

// `interactive` DRAWS THE HOVER, and it is opt-in rather than automatic. The mockups set
// `cursor:pointer` on roster rows because the whole row opens the tenant, and on capabilities
// rows they set a hover with no pointer because nothing opens. A hover that suggests a click
// which does not exist is a dead affordance, so the call site says which it is.
export function Tr({ children, interactive }: { children: ReactNode; interactive?: boolean }) {
  return (
    <tr
      className={`border-b border-border last:border-b-0 ${
        interactive ? "transition-colors duration-150 ease-out hover:bg-surface-raised" : ""
      }`}
    >
      {children}
    </tr>
  );
}

export function Td({ children, className }: { children: ReactNode; className?: string }) {
  return <td className={`px-4 py-3.5 align-top ${className ?? ""}`}>{children}</td>;
}

// ---------------------------------------------------------------------------
// TREATMENT 4: THE CARD PER ITEM
// ---------------------------------------------------------------------------
//
// Tenant Monitors and Analyses give each item its own bordered card with internal padding rather
// than a ruled row, because each item carries a BLOCK of facts (thresholds, a contract grid, a
// stats rail) instead of a line of them. Ruled rows would put a card's worth of content between
// two hairlines and the page would read as one long undifferentiated list.
//
// `muted` IS THE MOCKUPS' DASHED VARIANT, and it carries meaning rather than decoration: a dashed
// border on the raised surface is how both mockups draw a monitor that is AVAILABLE but not
// provisioned for this tenant, and an analysis that is declared but not deployed. Solid means it
// is running; dashed means it is not. That distinction is the whole point of the Available
// section, so it is a prop rather than a class the call site remembers.
export function ItemCard({ children, muted }: { children: ReactNode; muted?: boolean }) {
  return (
    <div
      className={`rounded-lg border p-4 ${
        muted ? "border-dashed border-border bg-surface-raised" : "border-border bg-surface"
      }`}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// THE FILTER BAR: a segmented group, and the chips ARE the counts
// ---------------------------------------------------------------------------
//
// THE MOCKUP DELETES A DUPLICATE RATHER THAN INFORMATION. The alerts inbox has no stat strip: its
// four lifecycle counts live inside the filter group, so each chip is both the number and the
// control that filters to it. The console rendered the same four numbers TWICE on one screen, as
// a StatStrip above and as outline chips below it, and B2 drops the strip.
//
// STILL LINKS, NEVER BUTTONS. Unchanged from the outline version: a link works with no
// JavaScript, its target shows in the status bar before it is clicked, and the active chip links
// back to the unfiltered list so no chip is ever inert.
export function FilterBar({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-2">{children}</div>;
}

// The segmented container: the mockups' 9px radius with a 3px inset, which is what makes the
// active chip read as sitting INSIDE a control rather than floating beside its siblings.
export function FilterGroup({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-wrap gap-1 rounded border border-border bg-surface p-[3px]">
      {children}
    </div>
  );
}

export function FilterChip({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: ReactNode;
}) {
  return (
    <a
      href={href}
      aria-current={active ? "page" : undefined}
      className={`text-caption rounded-sm px-3 py-1.5 font-medium transition-colors duration-150 ease-out ${
        active
          ? "bg-primary text-primary-foreground"
          : "text-foreground-muted hover:bg-muted hover:text-foreground"
      }`}
    >
      {children}
    </a>
  );
}

// The mockups' `.fdrop`: surface, hairline, the 9px interactive radius, muted text. Shared as a
// STRING rather than a component because it dresses native <select> and <button> elements, which
// a wrapper would have to forward every attribute to for no gain.
export const CONTROL_CLASS =
  "text-caption rounded border border-border bg-surface px-3 py-2 text-foreground transition-colors duration-150 ease-out hover:border-border-strong disabled:text-foreground-subtle disabled:hover:border-border";

// ---------------------------------------------------------------------------
// THE BUTTON, which is a DIFFERENT recipe from the control above
// ---------------------------------------------------------------------------
//
// A SECOND CONSTANT RATHER THAN A REUSE OF CONTROL_CLASS, because the mockups draw two different
// things and collapsing them would lose the distinction. `.fdrop` is a filter: hairline border,
// muted text, hover moves the border one step (mockup-runs :39, mockup-alerts-inbox :52).
// `.btn` is an action: the STRONGER border to begin with, and hover moves the border AND the text
// to the accent (mockup-tenant-monitors :69-70). A filter narrows a list; a button writes a row.
//
// THIS REPLACES TEN HAND-ROLLED COPIES. EnableMonitor and DecisionControls each carried their own
// `rounded border border-border ... hover:bg-surface-raised`, which was neither of the mockups'
// two recipes: a background hover where the mockups move a border, on a plain border where the
// mockups use the strong one. Two files agreeing by coincidence is how a recipe drifts.
export const BUTTON_CLASS =
  "text-caption rounded border border-border-strong bg-surface px-3.5 py-1.5 font-medium text-foreground-muted transition-colors duration-150 ease-out hover:border-primary hover:text-primary disabled:opacity-50 disabled:hover:border-border-strong disabled:hover:text-foreground-muted";

// `.btn.primary`: solid accent, and it is reserved for the action a surface exists to perform.
// Today that is Enable, which writes an IMMUTABLE reporting timezone, so being unmistakable is
// worth more here than restraint. Anything that is merely available stays on BUTTON_CLASS.
export const BUTTON_PRIMARY_CLASS =
  "text-caption rounded border border-primary bg-primary px-3.5 py-1.5 font-medium text-primary-foreground transition-colors duration-150 ease-out hover:opacity-90 disabled:opacity-50";

// ---------------------------------------------------------------------------
// THE STAT CARDS: the fleet overview's treatment, and ONLY the fleet overview's
// ---------------------------------------------------------------------------
//
// Four bordered cards in a grid, each a quiet label over a 24px figure with an optional detail
// line. text-display IS the mockups' `.stat .v` (24px, 600, tabular) at the house token, so the
// size is not hand-picked.
//
// StatStrip ABOVE IS NOT REPLACED, and that is deliberate rather than an oversight. The overview
// is the ONLY mockup with stats of any kind: the alerts inbox puts its counts in the filter
// chips, and the tenant page's mockup carries a meta line and a freshness pill instead. Giving
// every page stat cards because one page has them is the same error as giving every page the
// runs panel, in the other direction.
//
// B3 EXTENDED THIS TO EVERY STAT SURFACE, and the earlier sentence here said the opposite: it
// reserved the cards for the fleet overview and kept the inline strip on the tenant Overview tab
// and the alert detail page. That was right about not inventing a treatment and wrong about what
// it produced. One untreated tab inside a page whose other four are cards, tables and panels
// reads as unfinished, and the uniformity error worth avoiding was making every page look like
// runs, not leaving gaps. Stat cards ARE this system's treatment for stats, so a stat surface
// gets them. StatStrip and Stat are deleted; see the note where they used to live.
//
// `columns` EXISTS BECAUSE THE THREE SURFACES CARRY THREE, FOUR AND FIVE FIGURES. At a fixed
// four the tenant Overview's five stats render as four plus a dangling card and the alert
// detail's three leave a hole, and the alternative was dropping a figure, which is content
// rather than layout. A parameter on an established component is not a new treatment.
//
// THE CLASS NAMES ARE WRITTEN OUT, NOT INTERPOLATED. Tailwind scans source text for complete
// class names, so `lg:grid-cols-${columns}` would emit nothing at all and every grid would
// silently fall back to the two-column breakpoint. That is the same class of defect as
// hover:bg-surface-2, which is why this is a lookup rather than a template string.
const STAT_COLUMNS: Record<3 | 4 | 5, string> = {
  3: "lg:grid-cols-3",
  4: "lg:grid-cols-4",
  5: "lg:grid-cols-5",
};

export function StatCards({
  children,
  columns = 4,
}: {
  children: ReactNode;
  columns?: 3 | 4 | 5;
}) {
  return (
    <div className={`grid gap-3 sm:grid-cols-2 ${STAT_COLUMNS[columns]}`}>{children}</div>
  );
}

export function StatCard({
  label,
  value,
  detail,
  warn,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  warn?: boolean;
}) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <p className="text-caption text-foreground-subtle">{label}</p>
      <p className={`text-display mt-1.5 tabular-nums ${warn ? "text-warning" : "text-foreground"}`}>
        {value}
      </p>
      {detail ? <p className="text-caption mt-1 text-foreground-muted">{detail}</p> : null}
    </div>
  );
}

// The mockups' mono tag: a machine value shown as itself. Used for refusal reasons here, and
// for thresholds, capability ids and the refusal vocabulary on the Phase B2 pages.
// NO DOT AND NO TONE. It is not a status, so giving it one would say something false.
export function MonoChip({ children }: { children: ReactNode }) {
  return (
    <span className="text-micro rounded-sm border border-border bg-muted px-2 py-0.5 font-mono text-foreground-muted">
      {children}
    </span>
  );
}

// NameWithId WAS HERE AND IS DELETED. It stacked a plain name over its internal
// id as a self-contained block, which stopped working once metadata moved under
// the subject: the id now sits in each row's `meta` line alongside cadence,
// timezone and rung, because those are all the same KIND of fact and splitting
// one of them into its own component made it read as a different kind. The D4
// requirement it served — plain-language name AND internal id, never the id alone
// — still holds on every screen; it is just no longer a component.

// Rendered when the BFF cannot be reached. NAMES the service, because "something
// went wrong" sends an operator to the wrong system.
// The service-down notice, which is a banner for the same reason Attention is: it is laid over
// a page rather than being one of the objects the page is built from. Same 9px, same rule.
//
// THIS IS THE ONLY ERROR STATE IN THE CONSOLE, AND THERE IS NO LOADING STATE AT ALL. No
// loading.tsx exists anywhere under the Synapse tree, so every page blocks on its fetches and
// renders nothing until the BFF answers. That is a structural change rather than a visual one,
// which is why B3 did not add one while restyling everything around it.
export function SynapseDown({ message }: { message: string }) {
  return (
    <div className="rounded border border-[var(--warning-line)] bg-[var(--warning-bg)] p-4">
      <p className="text-body-strong text-warning">
        The Synapse service is not reachable.
      </p>
      <p className="text-caption mt-1 text-warning/80">{message}</p>
    </div>
  );
}

// A gap in the data, rendered as itself rather than as a blank (D5/D6). Carries
// the reason, so a reader learns WHY the row is missing instead of wondering
// whether the screen is broken.
// Unavailable WAS HERE AND IS DELETED. Its only call site was the tenant page's
// "Why each product was refused" row, whose body described synapse.run.detail,
// counts_by_reason() and a Plan-signature change — engineering backlog rendered to
// an operator. The row is gone, so the component is dead code rather than a
// primitive waiting for a second use.
//
// THE BACKLOG IT DESCRIBED IS NOW DONE: the Plan signature returns
// refusals, migration 0005 stores them, and refusalSentence() below renders the
// answer that row was apologising for not having. It is still not coming back —
// the refusal now belongs ON the monitor's own line, not in a row of its own.

// Singular/plural without a dependency. "1 tenants" and "1 actions" were on both Synapse
// screens; a helper is cheaper than remembering the ternary at every call site.
//
// THE `${one}s` DEFAULT FAILS ON IRREGULARS, SILENTLY AND IN PRODUCTION. It shipped
// "43 seriess refused" on the tenant Monitors tab, because the plural of "series" is
// "series" and nothing here knows that. PASS THE THIRD ARGUMENT for any word that does
// not simply take an s: plural(n, "series", "series"). The default is right for day,
// alert, monitor, product and run, which is why it survived this long.
export function plural(n: number, one: string, many?: string): string {
  return `${n} ${n === 1 ? one : (many ?? `${one}s`)}`;
}

// THE MODE, said once, in the header of every Synapse screen. Grey, not green and not amber:
// silent mode is neither good news nor a problem, it is the state the whole plane is in. The
// word "rung" never appears in the UI — it is the internal name for this and stays in the code,
// the API (`AnalysisState.rung`) and the database.
export function SilentModePill() {
  return <Tag tone="mute">Silent mode</Tag>;
}

export function daysSince(iso: string | null): number | null {
  if (!iso) return null;
  return Math.floor((Date.now() - new Date(`${iso}T00:00:00Z`).getTime()) / 86_400_000);
}

// ---------------------------------------------------------------------------
// The refusal breakdown (synapse.run.refusals, migration 0005)
// ---------------------------------------------------------------------------
//
// THIS IS WHAT RETIRED THE "unknown" TONE'S REASON FOR EXISTING on run rows. A
// zero-action run used to be un-interpretable: "looked and found nothing" and
// "could not assess anything" were the same row. The orchestrator now records
// WHICH, so the screen can say it instead of hedging.
//
// NOT NULL IN THE DATABASE (migration 0005): a run row always carries a map, and an
// empty one means no refusals were recorded. "This run assessed nothing at all" is
// what the outcome chip says, not a second encoding here.
//
// STILL OPTIONAL IN THIS TYPE, deliberately. The BFF, the orchestrator and this app
// deploy separately, so a response may predate the column. Absent is not the same as
// empty: empty asserts "nothing was refused", absent asserts nothing at all, and only
// one of those is safe to render as silence.
export type Refusals = Record<string, number> | null;

// Operator phrasing for the closed vocabulary in synapse.core.stockout_risk.
// RefusalReason. Deliberately plain: "series_too_stale" is the wire value and
// belongs in the code, not on a screen someone reads at 09:00.
const REASON_LABEL: Record<string, string> = {
  series_too_stale: "sales data too old",
  no_observations_in_window: "no recent sales",
  no_stock_quantity: "no stock figure",
  no_stock_on_hand: "no stock on hand",
  feed_stale: "sales feed has stopped",
  no_sale_history: "no sales data ever received",
  too_few_observations: "too few sales days",
  no_positive_demand: "returns exceeded sales",
};

// AN UNKNOWN KEY RENDERS AS ITSELF, DE-UNDERSCORED, rather than as "unknown" or
// not at all. The BFF passes the database's JSONB straight through and owns no
// copy of the vocabulary, so a reason added to the analysis reaches this screen
// BEFORE this map knows about it. Showing the raw-ish key is a weaker statement
// than a label, and a weaker true statement beats a confident wrong one.
export function reasonLabel(key: string): string {
  return REASON_LABEL[key] ?? key.replace(/_/g, " ");
}

// The dominant reason and the total, or null when there is nothing to say.
// Ties break on the key so the phrasing is stable across renders of one row.
export function refusalSummary(
  refusals: Refusals,
): { total: number; top: string; count: number } | null {
  if (!refusals) return null;
  const entries = Object.entries(refusals).filter(([, n]) => n > 0);
  if (entries.length === 0) return null;
  entries.sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const total = entries.reduce((sum, [, n]) => sum + n, 0);
  const [top, count] = entries[0]!;
  return { total, top, count };
}

// "12 positions refused as stale", the per-monitor line Phase A's item 5a wanted
// and could not have. Names the DOMINANT reason and, when there are others,
// says so rather than implying the total is all one cause.
//
// THE NOUN IS "position" AND IT USED TO BE "series", WHICH WAS WRONG FOR BOTH ANALYSES.
// The number comes from counts_by_reason in synapse/src/synapse/core/refusal.py, whose own
// docstring reads "How many positions were refused", and both analyses feed it the same shape:
// DeadStockRow and StockoutRiskRow are each one row per position, keyed by store and sku.
//
// "series" looked right for stockout_risk because a daily series is what that analysis READS.
// It is not what it REFUSES. A tenant reading "12 series refused" on a dead-stock monitor was
// being told about a unit that analysis has no concept of.
//
// NO THIRD ARGUMENT NEEDED NOW, and that is worth saying because the old line had one: the
// plural of "series" is "series", so it had to be passed twice to stop plural() emitting
// "43 seriess". "position" takes the default.
export function refusalSentence(refusals: Refusals): string | null {
  const summary = refusalSummary(refusals);
  if (!summary) return null;
  const head = `${plural(summary.count, "position")} refused, ${reasonLabel(summary.top)}`;
  const rest = summary.total - summary.count;
  return rest > 0 ? `${head}, and ${rest} for other reasons` : head;
}

// One entry per stored reason, biggest first, ties broken on the key so the order is stable
// across renders. This is the WHOLE breakdown rather than refusalSummary's dominant reason: a
// fleet table's status cell had room for one, a run row has room for all of them, and the reason
// a monitor stayed quiet is the question the runs screen is most often opened to answer.
//
// LIVES HERE RATHER THAN ON THE RUNS PAGE because the outcome ladder below reads it, and Phase
// B2's tenant Runs tab renders the same chips from the same rows.
export function skipChips(refusals: Refusals): Array<[string, number]> {
  if (!refusals) return [];
  return Object.entries(refusals)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

// ---------------------------------------------------------------------------
// A run's wall clock, in the zone the run itself recorded
// ---------------------------------------------------------------------------
//
// started_at IS AN INSTANT AND A CLOCK TIME IS NOT. synapse.run.timezone is snapshotted onto
// each run by the orchestrator, and Phase B1 projects it precisely so this can be rendered
// without guessing: a 03:00 Asia/Kolkata sweep is 21:30 UTC on the PREVIOUS day, so rendering
// the instant in UTC under a slot date of the 9th would show 21:30 beside "2026-08-09" and read
// as a bug. The zone is not decoration.
//
// AN UNUSABLE ZONE FALLS BACK TO UTC AND SAYS SO. The column is TEXT with only a non-empty
// CHECK, so nothing in the database guarantees an IANA name; Intl throws RangeError on a bad
// one, which would take the whole page down. The fallback labels itself, so a reader is never
// shown a time in a zone they were not told about.
//
// NULL FOR AN UNPARSEABLE INSTANT, so a caller omits the time rather than printing "Invalid
// Date" at an operator.
//
// THE LOCALE IS en-IN, AND IT IS LOAD-BEARING RATHER THAN COSMETIC. `timeZoneName: "short"`
// resolves through CLDR PER LOCALE, so the same zone renders differently depending on who is
// asking. Measured:
//
//                        en-GB        en-IN
//     Asia/Kolkata       GMT+5:30     IST
//     Europe/London      BST          GMT+1
//     Europe/Warsaw      CEST         GMT+2
//     America/New_York   GMT-4        GMT-4
//
// NO LOCALE GIVES AN ABBREVIATION EVERYWHERE, so this is a choice about which zones read well
// rather than a bug with a correct fix. Every production tenant is Asia/Kolkata, so en-IN is
// the one that serves the fleet that exists; elsewhere it degrades to a UTC offset, which is
// less friendly and never wrong. It was en-GB, which rendered the sweep as "03:00 GMT+5:30".
//
// THIS BECOMES A REAL SETTING IF THE FLEET SPANS REGIONS. At that point a console-wide constant
// is the wrong shape: the honest answer is the viewer's own locale, or the tenant's, and either
// is a decision rather than a default.
const CONSOLE_LOCALE = "en-IN";

export function wallClock(
  iso: string,
  timeZone: string,
  { seconds = false }: { seconds?: boolean } = {},
): { time: string; zone: string } | null {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return null;

  const options: Intl.DateTimeFormatOptions = {
    hour: "2-digit",
    minute: "2-digit",
    ...(seconds ? { second: "2-digit" } : {}),
    hourCycle: "h23",
    timeZoneName: "short",
  };

  for (const zone of [timeZone, "UTC"]) {
    let parts: Intl.DateTimeFormatPart[];
    try {
      parts = new Intl.DateTimeFormat(CONSOLE_LOCALE, {
        ...options,
        timeZone: zone,
      }).formatToParts(at);
    } catch {
      continue;
    }
    const time = parts
      .filter((part) => part.type === "hour" || part.type === "minute" || part.type === "second")
      .map((part) => part.value)
      .join(":");
    const named = parts.find((part) => part.type === "timeZoneName");
    return { time, zone: named ? named.value : zone };
  }
  return null;
}

// ---------------------------------------------------------------------------
// WHAT A RUN CAME TO: the outcome ladder
// ---------------------------------------------------------------------------
//
// REPLACES A UNIFORM GREEN "completed" ON EVERY ROW, which was the raw `outcome` column shown
// as itself. 'satisfied' means the DECLARATION resolved and the analysis ran; it says nothing
// about whether anything was found, so every row wore the same green pill whether it raised six
// alerts, suppressed one as a repeat, or could not assess a single series.
//
// FOUR INPUTS AND NO INFERENCE: outcome, actions_proposed, actions_appended and the stored
// refusal breakdown. Nothing here is derived from a count the database does not hold.
//
// THE dead_stock TRAP IS GONE, AND ROW 10 STAYS ANYWAY. This comment used to read that
// "_plan_dead_stock returns refusals={} on every run: dead_stock has NO refusal concept", which
// was true and is now false: the analysis refuses when a position fails its stock premise and
// when the tenant's sales feed has stopped or never started, and registry.py counts those onto
// the run row exactly as stockout_risk's have always been.
//
// SO AN EMPTY MAP NOW MEANS ONE THING for every analysis: this run refused nothing. Row 10 is
// kept because zero proposed with nothing refused is still a statement of the count rather than
// a diagnosis, and that is now a genuinely quiet catalogue rather than an unknown.
export type RunOutcomeFacts = {
  outcome: string | null;
  actions_proposed: number | null;
  actions_appended: number | null;
  refusals: Refusals | undefined;
};

export function runOutcomeTag(run: RunOutcomeFacts): { label: string; tone: Tone } {
  // 1. Claimed and never completed. The next run for the slot adopts and finishes it.
  if (run.outcome === null) return { label: "unfinished", tone: "mute" };
  // 2. An exception during the run.
  if (run.outcome === "failed") return { label: "run failed", tone: "stop" };
  // 3. No analysis is declared under this id at all.
  if (run.outcome === "undeclared") return { label: "no such monitor", tone: "mute" };
  // 4. At least one capability requirement did not resolve, so the monitor never assessed
  //    anything. NOT "found nothing", which would claim it looked. Matches the wording the
  //    tenant surfaces already use for this condition.
  if (run.outcome === "blocked") return { label: "waiting for data", tone: "unknown" };
  // An outcome this build does not know renders AS ITSELF rather than being filed under one of
  // the four. The BFF passes the column through and the vocabulary can grow ahead of this app.
  if (run.outcome !== "satisfied") return { label: run.outcome, tone: "mute" };

  const proposed = run.actions_proposed;
  const appended = run.actions_appended;

  // 5. Satisfied with no counts. The constraint permits it; the screen states it.
  if (proposed === null || appended === null) return { label: "no result recorded", tone: "mute" };

  if (proposed > 0) {
    // 6. Something was recorded. COUNTS appended, not proposed: the tag says how many alerts
    //    now exist for someone to act on, and the detail line carries both numbers.
    if (appended > 0) return { label: `${plural(appended, "alert")} raised`, tone: "stop" };
    // 7. Every proposal was a repeat of a finding already recorded for this slot, so the
    //    idempotency index suppressed it. That is the system working, not a quiet failure.
    return { label: "no new alerts", tone: "good" };
  }

  const skips = skipChips(run.refusals ?? null);
  // 8. KEYED ON PRESENCE, NOT DOMINANCE, and the mockup's own example is why: a run refusing 3
  //    series as stale and 63 for no observations reads as "data too old". Staleness is the more
  //    specific and more actionable diagnosis, so it wins wherever it appears at all.
  if (skips.some(([reason, n]) => reason === "series_too_stale" && n > 0)) {
    return { label: "found nothing - data too old", tone: "unknown" };
  }
  // 9. Refused everything for some other stored reason.
  if (skips.length > 0) return { label: "found nothing - no data", tone: "unknown" };
  // 10. Zero proposed and nothing recorded as refused. Every analysis can refuse now, so this
  //     really does mean "it looked and found nothing", which is a statement of the count and
  //     deliberately still not a diagnosis.
  return { label: "no alerts raised", tone: "mute" };
}

// PROPOSED AND RECORDED, SHOWN SEPARATELY WHENEVER THERE WAS ANYTHING TO PROPOSE. They differ
// with nothing wrong: a repeat of a finding already recorded for the same slot is suppressed by
// the idempotency index rather than duplicated, so "1 proposed" and "0 recorded" is the index
// doing its job. Collapsing them when equal was considered and rejected: the pair is the point,
// and a line that changes shape depending on whether two numbers happen to match is harder to
// read than one that always says the same thing.
//
// NULL WHEN NOTHING WAS PROPOSED. The tag already carries that case, and repeating it here as
// "0 proposed" would be a second, quieter statement of the same fact.
export function runDetail(run: RunOutcomeFacts): string | null {
  const proposed = run.actions_proposed;
  const appended = run.actions_appended;
  if (proposed === null || proposed === 0) return null;
  if (appended === null) return `${proposed} proposed, no record of what was kept`;
  return appended === 0
    ? `${proposed} proposed - suppressed as repeat (already recorded)`
    : `${proposed} proposed - ${appended} recorded`;
}

// ---------------------------------------------------------------------------
// Alert lifecycle (synapse.action_events, migration 0006)
// ---------------------------------------------------------------------------
//
// THIS FILE NO LONGER DERIVES A LIFECYCLE STATE, AND THAT IS THE POINT OF B2a.
//
// `alertState()` used to live here and recompute the state from the raw
// lifecycle columns. It was one of THREE derivations: this one, the SQL CASE the
// inbox uses, and a third inline copy inside the fleet roster's open-alert
// count. Three copies of one rule is three chances to disagree, and they did:
// the inbox read "Open 6, Acknowledged 5" while the fleet and tenant pages both
// read 11.
//
// SQL IS THE SINGLE AUTHORITY, because only SQL can filter and count fleet-wide,
// and a count that disagrees with the list it heads is worse than no count. So
// the server derives `lifecycle_state` once (reads.py `_LIFECYCLE_STATE`) and
// every statement that returns an alert carries it. This module RENDERS that
// value and never computes one.
//
// PER TARGET, NOT PER ALERT, which is what the server's join encodes. An
// operator who snoozes means "stop showing me this product at this store", so
// tomorrow's detection of the same thing inherits the decision rather than
// arriving fresh.
export type AlertState = "open" | "snoozed" | "dismissed" | "acknowledged";

const ALERT_STATES: readonly AlertState[] = ["open", "snoozed", "dismissed", "acknowledged"];

// THE ONE NARROWING POINT, called once per page where JSON enters.
//
// The wire carries a string, and this build cannot promise the server will never
// grow a fifth state. Rather than typing the row field as AlertState and lying,
// the row keeps `string` and this converts, returning null for anything
// unrecognised so the caller can render the raw word instead of filing it under
// a state it does not mean. Everything downstream of this call is typed, so a
// renamed or mistyped state is a compile error rather than a silent miscount.
export function asAlertState(raw: string): AlertState | null {
  return (ALERT_STATES as readonly string[]).includes(raw) ? (raw as AlertState) : null;
}

const STATE_TONE: Record<AlertState, Tone> = {
  open: "unknown",
  snoozed: "mute",
  dismissed: "mute",
  acknowledged: "good",
};

// Distinct from the refusal REASON_LABEL above: that one names why a MONITOR
// could not assess a position, this one names why an OPERATOR dismissed an
// alert. Same word, two vocabularies, and merging them would let a monitor's
// refusal render as a human decision.
const DISMISS_REASON_LABEL: Record<string, string> = {
  seasonal: "seasonal",
  display_stock: "display stock",
  discontinued: "discontinued",
  wrong_data: "wrong data",
};

// ACKNOWLEDGED IS NOT OPEN, and B2a reversed this. It previously returned true
// for acknowledged on the grounds that acknowledging leaves an alert standing.
//
// THE FOUR STATES ARE MUTUALLY EXCLUSIVE. If acknowledged also counted as open,
// the inbox chips would sum above the total number of rows and no arrangement of
// them could be made to add up. Open means "needs a decision"; snoozed,
// acknowledged and dismissed are all decisions, and all three are excluded.
//
// If "seen, still working" is ever wanted it is a NEW VERB, not a
// reinterpretation of this one.
//
// TAKES AlertState, NOT string. That is the type-level half of the same defect:
// the union is narrow so a renamed or mistyped state fails to compile rather
// than quietly falling through to false. Callers narrow at the wire with
// asAlertState.
export function isOpen(state: AlertState): boolean {
  return state === "open";
}

// ONE RENDERING, ONE SOURCE OF THE STATE. Every alert-bearing endpoint now
// serves `lifecycle_state`, so this is handed a state rather than deriving one.
// The tone map, the word and the suffixes are one thing because there is only
// one path through here.
function stateTag(state: AlertState, reason: string | null, snoozedUntil: string | null) {
  const suffix =
    state === "snoozed" && snoozedUntil
      ? ` until ${snoozedUntil}`
      : state === "dismissed" && reason
        ? ` · ${DISMISS_REASON_LABEL[reason] ?? reason}`
        : "";
  return (
    <Tag tone={STATE_TONE[state]}>
      {state}
      {suffix}
    </Tag>
  );
}

// THE ONE STATE TAG. `ServerStateTag` was its twin and is deleted: with the
// state served rather than derived, two components rendering identically from
// one field would be a worse version of the duplication B2a exists to remove.
//
// TAKES AlertState. A caller holding a raw wire string narrows it with
// asAlertState first and renders the raw word itself when that returns null, so
// a fifth server state shows up as the word rather than being filed under one of
// the four. See UnknownStateTag.
export function AlertStateTag({
  state,
  reason,
  snoozedUntil,
}: {
  state: AlertState;
  reason: string | null;
  snoozedUntil: string | null;
}) {
  return stateTag(state, reason, snoozedUntil);
}

// A state this build does not know about, rendered AS ITSELF in the neutral
// tone. Separate from AlertStateTag rather than a branch inside it, because the
// two have genuinely different contracts: one is exhaustive over a closed union,
// this one is the escape hatch for a wire value that escaped it.
export function UnknownStateTag({ state }: { state: string }) {
  return <Tag tone="mute">{state}</Tag>;
}
