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

export function Tile({ n, label, warn }: { n: ReactNode; label: string; warn?: boolean }) {
  return (
    <div className="rounded-md bg-surface-raised p-4">
      <p className={`text-display ${warn ? "text-warning" : "text-foreground"}`}>{n}</p>
      <p className="text-caption text-foreground-muted">{label}</p>
    </div>
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
// either "looked and found no risk" or "refused every product as stale", and
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

// D4: plain-language name, internal id alongside. The internal id is what
// appears in logs, in synapse.run.analysis_id and in every action's provenance —
// a screen showing only the friendly name makes a log line unsearchable from the
// UI that produced it.
export function NameWithId({ name, id }: { name: string; id: string }) {
  return (
    <div>
      <p className="text-body-strong text-foreground">{name}</p>
      <p className="text-micro font-mono text-foreground-subtle">{id}</p>
    </div>
  );
}

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
export function Unavailable({ what, because }: { what: string; because: string }) {
  return (
    <tr className="border-b border-border last:border-b-0 align-top">
      <td className="text-body py-3 text-foreground-muted">{what}</td>
      <td className="py-3 text-right">
        <Tag tone="unknown">not recorded yet</Tag>
      </td>
      <td className="text-caption max-w-prose py-3 pl-4 text-foreground-muted">{because}</td>
    </tr>
  );
}

export function daysSince(iso: string | null): number | null {
  if (!iso) return null;
  return Math.floor((Date.now() - new Date(`${iso}T00:00:00Z`).getTime()) / 86_400_000);
}
