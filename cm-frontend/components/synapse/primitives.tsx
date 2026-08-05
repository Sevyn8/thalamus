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
// The app fills the window; the content does not. Without this every screen ran
// edge to edge on a 1900px monitor and a label sat half a screen from its value,
// which is a proximity failure no amount of correct colour can rescue.
//
// 840px, LEFT-ALIGNED, and not `mx-auto`. Two precedents exist in this repo and
// they disagree — app/my-ithina uses max-w-5xl (1024px) and profile uses
// max-w-3xl (768px), both centred — so there is no scale convention to honour and
// no reason to round 840 up to max-w-4xl (896px) for tidiness. 840 was measured
// against real data in a real mockup; 56px of it is the proximity being bought.
//
// PATTERNS.md SPECIFIES NO CONTAINER WIDTH. It specifies `p-6` outer padding and
// names PageHeader as the page wrapper — checked before writing this, because the
// rule is to grep the docs for the mechanism rather than to assume.
//
// px-6 ON THE OUTER, max-w ON THE INNER, so 840 is the CONTENT width and the text
// left edge lines up with PageHeader's own px-6. The six Synapse screens had no
// horizontal padding at all before this: PageHeader was inset and the body was
// flush to the sidebar, so a page did not even align with its own title.
export function Column({ children }: { children: ReactNode }) {
  return (
    <div className="px-6 pb-12">
      <div className="max-w-[840px] space-y-6">{children}</div>
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
            attention ? "text-body-strong text-amber-700 dark:text-amber-300" : "text-body-strong"
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
// max-w-prose rather than a hand-picked character count: it is the house token,
// already used nine times, and it replaces the three different ch values the
// mockup reached for.
export function Footnote({ children }: { children: ReactNode }) {
  return <p className="text-caption max-w-prose text-foreground-subtle">{children}</p>;
}

// The amber banner for the thing that needs a person. NOT a row that looks like
// the others — that was the R1 failure: the one item requiring action was styled
// identically to the three that did not.
export function Attention({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="rounded-md border border-amber-200 bg-amber-50 p-4 dark:border-amber-500/30 dark:bg-amber-500/15">
      <p className="text-body-strong text-amber-700 dark:text-amber-300">{title}</p>
      <p className="text-caption mt-1 max-w-prose text-amber-700/80 dark:text-amber-300/80">
        {detail}
      </p>
    </div>
  );
}

// R2 had no way back. "My Sevyn8" was the only upward link in the chrome and it
// goes somewhere else entirely, so a tenant panel was a dead end.
export function Breadcrumb({ tenant }: { tenant: string }) {
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
      <span className="text-foreground">{tenant}</span>
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
// either "looked and found no risk" or "found nothing — sales data too old", and
// until synapse.run.detail is populated NOTHING IN THE DATA DISTINGUISHES THEM.
// Rendering both as "0 found" would be a guess presented as a result; rendering
// both as "cannot assess" would be a different guess. The third state says
// exactly what is true: zero, and we cannot tell which.
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

export function Tag({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <Chip tone={TONE_TO_CHIP[tone]}>{children}</Chip>;
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
    <div className="rounded-md border border-amber-200 bg-amber-50 p-4 dark:border-amber-500/30 dark:bg-amber-500/15">
      <p className="text-body-strong text-amber-700 dark:text-amber-300">
        The Synapse service is not reachable.
      </p>
      <p className="text-caption mt-1 text-amber-700/80 dark:text-amber-300/80">{message}</p>
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
