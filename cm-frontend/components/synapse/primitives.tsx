// Shared markup for the Synapse superadmin screens. Server-safe: no hooks, no
// "use client" — every Synapse page is a server component so the BFF stays
// unreachable from the browser.
//
// FOLLOWS PATTERNS.md: the typography scale (text-display / text-body /
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
export function Column({ children }: { children: ReactNode }) {
  return (
    <div className="px-6 pt-6">
      <div className="space-y-6">{children}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stats: a strip, not four billboards
// ---------------------------------------------------------------------------
//
// These are CONTEXT, not the point of the page. As `text-display` numbers in
// filled cards they outweighed the data they were describing. Inline, quiet, and
// only the one that means something carries colour — a page where four figures
// are all emphasised has emphasised nothing.
export function StatStrip({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap gap-x-8 gap-y-3">{children}</div>;
}

export function Stat({ n, label, warn }: { n: ReactNode; label: string; warn?: boolean }) {
  return (
    <div>
      <p className={`text-heading ${warn ? "text-warning" : "text-foreground"}`}>{n}</p>
      <p className="text-caption text-foreground-muted">{label}</p>
    </div>
  );
}

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

// ---------------------------------------------------------------------------
// A list row: metadata WITH its subject, status alone on the right
// ---------------------------------------------------------------------------
//
// `daily · Asia/Kolkata · shadow` belongs under the name it describes, not at the
// far edge of the screen. Only the status goes right, because it is the only
// thing a reader scans a column of.
//
// `attention` carries the amber. Two analyses where one works and one has never
// run must not look identical — the hierarchy IS the information.
export function Row({
  title,
  meta,
  right,
  note,
  attention,
}: {
  title: ReactNode;
  meta?: ReactNode;
  right?: ReactNode;
  note?: string;
  attention?: boolean;
}) {
  return (
    <div className="flex items-start gap-4 border-b border-border py-3 last:border-b-0">
      <div className="min-w-0 flex-1">
        <div
          className={
            attention ? "text-body-strong text-warning" : "text-body-strong"
          }
        >
          {title}
        </div>
        {meta ? <p className="text-caption mt-0.5 text-foreground-muted">{meta}</p> : null}
      </div>
      {right || note ? (
        <div className="shrink-0 text-right">
          {right}
          {note ? (
            <p className="text-micro mt-1 text-foreground-subtle">{note}</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

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
export function Attention({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="rounded-md border border-[var(--warning-line)] bg-[var(--warning-bg)] p-4">
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
// SLICE 5b NARROWED WHEN THAT HEDGE IS NEEDED, and did not remove it. The run row
// now carries a refusal breakdown, so a run that refused series SAYS SO and the
// screen names the reason. The hedge still applies where the breakdown is null —
// a run that never reached its plan, or one predating migration 0005 — which is
// exactly the case where the data genuinely cannot tell which.
export type Tone = "good" | "unknown" | "mute" | "stop";

// DELEGATES TO THE HOUSE CHIP rather than restating its recipe. Chips.tsx already
// carries the light-base + dark:-override pairs PATTERNS.md specifies; a second
// copy here would be a second source of truth for what a status chip looks like,
// and the copy that drifts is always the one nobody is looking at.
const TONE_TO_CHIP: Record<Tone, ChipTone> = {
  good: "green",
  unknown: "amber",
  mute: "grey",
  stop: "red",
};

// `dot` FORWARDS TO Chip AND DEFAULTS TO TRUE, so every existing Synapse call site is unchanged.
// The mockups' status pills carry no dot; the runs page opts out, and the rest of the console
// follows in Phase B2 rather than being restyled from underneath 5c here.
export function Tag({
  tone,
  children,
  dot,
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

// ---------------------------------------------------------------------------
// THE PANEL: the mockups' one card treatment, as five parts
// ---------------------------------------------------------------------------
//
// Every mockup builds its content from the same object: a white surface on the page
// background, a hairline border, a raised header strip, ruled rows, and an optional
// quieter note along the bottom. It was hand-rolled on the runs page and nowhere else,
// which is why the runs page and the alerts inbox did not look like one product.
//
// RADIUS IS rounded-md (10px), NOT THE MOCKUPS' 14px, and this is a deliberate override.
// ver2's own index.css calls 10px the card radius; cm-frontend encodes that as --radius-md
// and uses `rounded-md` on 135 call sites against 2 for `rounded-lg`. Taking the mockups'
// 14px here would make Synapse the only surface in the product with a different card, which
// is the "odd ones out" failure the Column comment above exists to describe. The mockups are
// overruled on radius, as they are on monitor names.
export function Panel({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-md border border-border bg-surface">{children}</div>
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
export function SynapseDown({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-[var(--warning-line)] bg-[var(--warning-bg)] p-4">
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
// THE BACKLOG IT DESCRIBED IS NOW DONE (slice 5b): the Plan signature returns
// refusals, migration 0005 stores them, and refusalSentence() below renders the
// answer that row was apologising for not having. It is still not coming back —
// the refusal now belongs ON the monitor's own line, not in a row of its own.

// Singular/plural without a dependency. "1 tenants" and "1 actions" were on both Synapse
// screens; a helper is cheaper than remembering the ternary at every call site.
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

// "12 series refused as stale" — the per-monitor line Phase A's item 5a wanted
// and could not have. Names the DOMINANT reason and, when there are others,
// says so rather than implying the total is all one cause.
export function refusalSentence(refusals: Refusals): string | null {
  const summary = refusalSummary(refusals);
  if (!summary) return null;
  const head = `${plural(summary.count, "series")} refused — ${reasonLabel(summary.top)}`;
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
      parts = new Intl.DateTimeFormat("en-GB", { ...options, timeZone: zone }).formatToParts(at);
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
// THE dead_stock TRAP, and it is the reason row 10 exists. synapse.registry._plan_dead_stock
// returns `refusals={}` on every run: dead_stock has NO refusal concept, and registry.py says
// so directly, that "the run row's breakdown being empty must never be rendered as 'nothing was
// refused today' for an analysis that has no refusal concept". So an empty map cannot be read as
// "it looked and refused nothing", and a zero-action dead_stock run gets a neutral statement of
// the count rather than a diagnosis the data cannot support.
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
  // 10. Zero proposed and nothing recorded as refused. See the dead_stock note above: this is a
  //     statement of the count and deliberately not a diagnosis.
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
// PER TARGET, NOT PER ALERT. The BFF resolves the latest decision for
// (declaration_id, target), so a snooze taken yesterday covers today's new
// detection of the same product at the same store. That is what an operator
// means by "snooze"; a per-row state would evaporate on the next detection.
//
// A SNOOZE EXPIRES; A DISMISSAL DOES NOT. So "snoozed" is a function of the
// date and has to be recomputed on every render rather than stored.
export type Lifecycle = {
  lifecycle_verb: string | null;
  lifecycle_reason: string | null;
  lifecycle_snoozed_until: string | null;
};

export type AlertState = "open" | "snoozed" | "dismissed" | "acknowledged";

// `today` is injected rather than read here so a caller can pin it. Compared as
// ISO date strings: both sides are date-only, and Date parsing would drag a
// timezone into a comparison that has none.
export function alertState(row: Lifecycle, today: string): AlertState {
  if (row.lifecycle_verb === "dismissed" || row.lifecycle_verb === "dismiss") return "dismissed";
  if (row.lifecycle_verb === "snooze") {
    // A LAPSED SNOOZE IS OPEN AGAIN, and the row says so without anything having
    // written a second event. Nothing expires it in the database on purpose:
    // the decision was "quiet until this date", not "quiet, then noisy".
    return row.lifecycle_snoozed_until && row.lifecycle_snoozed_until >= today ? "snoozed" : "open";
  }
  if (row.lifecycle_verb === "acknowledge") return "acknowledged";
  return "open";
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

// ACKNOWLEDGED IS NOT CLOSED. It says somebody has seen this and left it
// standing — the difference between an unread queue and a handled one — so it
// still counts as open everywhere a count is taken.
//
// TAKES A STRING, not AlertState, so the fleet inbox can pass the state the BFF
// derived without a cast. An unrecognised value is NOT open: a state this build
// does not know about is one it cannot claim needs attention.
export function isOpen(state: string): boolean {
  return state === "open" || state === "acknowledged";
}

// ONE RENDERING, TWO SOURCES OF THE STATE. The tenant-scoped screens derive the
// state here from the raw lifecycle columns (alertState); the fleet inbox is
// handed a state the BFF already derived in SQL, because the list is FILTERED on
// it and a chip disagreeing with the filter that selected the row is worse than
// no chip. Both paths land on this function, so the tone map, the word and the
// suffixes stay one thing. Unifying the two derivations is Phase B.
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

export function AlertStateTag({ row, today }: { row: Lifecycle; today: string }) {
  return stateTag(alertState(row, today), row.lifecycle_reason, row.lifecycle_snoozed_until);
}

// The fleet inbox's tag. `state` arrives as a plain string from JSON rather than
// as AlertState, so an unrecognised value is rendered AS ITSELF in the neutral
// tone rather than coerced into one of the four: if the BFF ever grows a fifth
// state, a reader should see the word, not silently see it filed as "open".
export function ServerStateTag({
  state,
  reason,
  snoozedUntil,
}: {
  state: string;
  reason: string | null;
  snoozedUntil: string | null;
}) {
  if (!(state in STATE_TONE)) return <Tag tone="mute">{state}</Tag>;
  return stateTag(state as AlertState, reason, snoozedUntil);
}
