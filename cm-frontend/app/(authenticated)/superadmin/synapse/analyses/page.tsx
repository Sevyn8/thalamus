import { PageHeader } from "@/components/shared/PageHeader";
import {
  Column,
  Footnote,
  SectionHead,
  SynapseDown,
  Tag,
} from "@/components/synapse/primitives";
import { CAPABILITY_NAMES } from "@/lib/synapse/names";
import { SynapseUnavailable, synapseGet } from "@/lib/synapse/server-client";

// NEVER PRERENDER THIS PAGE. It reads SYNAPSE_BFF_URL and the caller's session at
// request time; prerendering executes it during `next build`, where neither
// exists, and bakes the resulting error notice into static HTML that the
// container then serves for ever. That shipped once — see lib/synapse/server-client.ts.
//
// scripts/assert-dynamic-routes.mjs fails the build if this route comes out
// static, so the directive cannot be silently dropped.
export const dynamic = "force-dynamic";

// E2 — what exists, what each needs, and the ceiling on what each may do.
//
// THIS SCREEN NEVER OFFERS AN EDIT. Declarations are git: an analysis, its
// thresholds and its ceiling are reviewed and merged, not typed into a console.
// A UI that could change a threshold would make the number unfalsifiable — the
// action log records which version produced each action, and that provenance is
// worthless if the version's meaning can move underneath it.

type ThresholdView = {
  name: string;
  days: number;
  fitted: boolean;
  stands_in_for: string | null;
};

type AnalysisView = {
  analysis_id: string;
  name: string;
  version: string;
  requires: string[];
  max_rung: string;
  thresholds: ThresholdView[];
  holdout_percent: number | null;
};

export default async function AnalysesPage() {
  let analyses: AnalysisView[];
  try {
    ({ analyses } = await synapseGet<{ analyses: AnalysisView[] }>("/analyses"));
  } catch (error) {
    if (error instanceof SynapseUnavailable) {
      return (
        <div>
          <PageHeader title="Monitors" subtitle="What Synapse watches for." />
          <Column>
            <SynapseDown message={error.message} />
          </Column>
        </div>
      );
    }
    throw error;
  }

  return (
    <div>
      <PageHeader
        title="Monitors"
        subtitle="Declared in the repository, reviewed and merged. This screen reads them; it authors nothing."
      />

      <Column>
        {analyses.map((a) => (
          <section key={a.analysis_id}>
            <SectionHead>{a.name}</SectionHead>

            {/* METADATA WITH ITS SUBJECT. The id, version, ceiling and holdout were
                split across a left block and a right-aligned cluster with the width
                of the monitor between them. */}
            <div className="mb-3 flex items-start gap-4">
              <div className="min-w-0 flex-1">
                <p className="text-caption font-mono text-foreground-muted">
                  {a.analysis_id} · {a.version}
                </p>
                <p className="text-body mt-1 text-foreground-muted">
                  Reads {a.requires.map((c) => CAPABILITY_NAMES[c] ?? c).join(" and ")}.
                </p>
              </div>
              <span className="flex shrink-0 items-center gap-2">
                {/* THE CEILING. What this analysis is PERMITTED to do, for any
                    tenant, ever — a property of its maturity rather than of any
                    customer, which is why it lives in code. Showing it is how an
                    operator sees that nothing can reach a client without reading
                    Python. */}
                {/* THE CEILING: the furthest this monitor may ever go, for any client. The
                    internal name for the value is a "rung" and the shadow rung is what the UI
                    calls silent mode — neither word is rendered. A value other than shadow has
                    no agreed plain name yet, so it renders as-is rather than being invented. */}
                <Tag tone={a.max_rung === "shadow" ? "mute" : "unknown"}>
                  {a.max_rung === "shadow" ? "Silent mode only" : `ceiling: ${a.max_rung}`}
                </Tag>
                {a.holdout_percent !== null && <Tag tone="mute">{a.holdout_percent}% held back</Tag>}
              </span>
            </div>

            {/* TWO COLUMNS. The threshold name and its value are one fact; the
                explanation sits under them rather than as a third column. */}
            <table className="w-full">
              <tbody>
                {a.thresholds.map((t) => (
                  <tr key={t.name} className="border-b border-border align-baseline last:border-b-0">
                    <td className="py-3 pr-4">
                      <p className="text-body font-mono">{t.name}</p>
                      {!t.fitted && (
                        /* RENDERED VERBATIM, NEVER SUMMARISED. Each sentence names
                           what the number substitutes for and why that cannot be
                           known — one cites a declined capability, another a
                           telemetry column that is NULL in Phase A. Summarising
                           turns a checkable statement into a shrug, and the honesty
                           is the only thing making these constants defensible. */
                        <p className="text-caption mt-1 max-w-prose leading-relaxed text-foreground-subtle">
                          {t.stands_in_for}
                        </p>
                      )}
                    </td>
                    <td className="py-3 text-right align-top whitespace-nowrap">
                      <span className="text-body font-mono">{t.days} days</span>
                      <span className="mt-1 block">
                        {t.fitted ? (
                          <Tag tone="good">measured</Tag>
                        ) : (
                          <Tag tone="unknown">a convention</Tag>
                        )}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ))}

        <Footnote>
          Every number on this page is a stated convention. None is derived from any tenant&apos;s
          data, and each says what it stands in for — fitting them needs capabilities that do not
          exist.
        </Footnote>
      </Column>
    </div>
  );
}
