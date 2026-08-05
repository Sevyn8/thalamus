import { PageHeader } from "@/components/shared/PageHeader";
import { NameWithId, SectionHead, SynapseDown, Tag } from "@/components/synapse/primitives";
import { CAPABILITY_NAMES } from "@/lib/synapse/names";
import { SynapseUnavailable, synapseGet } from "@/lib/synapse/server-client";

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
        <div className="space-y-6">
          <PageHeader title="Analyses" subtitle="What Synapse computes." />
          <SynapseDown message={error.message} />
        </div>
      );
    }
    throw error;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Analyses"
        subtitle="Declared in the repository, reviewed and merged. This screen reads them; it authors nothing."
      />

      {analyses.map((a) => (
        <section key={a.analysis_id}>
          <SectionHead>{a.name}</SectionHead>

          <div className="mb-3 flex items-start gap-3">
            <NameWithId name={a.name} id={`${a.analysis_id} ${a.version}`} />
            <span className="ml-auto flex items-center gap-2">
              {/* THE CEILING. What this analysis is PERMITTED to do, for any
                  tenant, ever — a property of its maturity rather than of any
                  customer, which is why it lives in code. Showing it is how an
                  operator sees that nothing can reach a client without reading
                  Python. */}
              <Tag tone={a.max_rung === "shadow" ? "mute" : "unknown"}>
                ceiling: {a.max_rung === "shadow" ? "watch only" : a.max_rung}
              </Tag>
              {a.holdout_percent !== null && (
                <Tag tone="mute">{a.holdout_percent}% held back</Tag>
              )}
            </span>
          </div>

          <p className="mb-3 text-body text-foreground-muted">
            Reads {a.requires.map((c) => CAPABILITY_NAMES[c] ?? c).join(" and ")}.
          </p>

          <table className="w-full text-body">
            <tbody>
              {a.thresholds.map((t) => (
                <tr key={t.name} className="border-b border-border last:border-b-0 align-top">
                  <td className="w-56 py-2">
                    <span className="text-micro font-mono">{t.name}</span>
                  </td>
                  <td className="w-20 py-2 text-micro font-mono">{t.days} days</td>
                  <td className="py-3 pl-4">
                    {t.fitted ? (
                      <Tag tone="good">measured from this tenant&apos;s data</Tag>
                    ) : (
                      <>
                        <Tag tone="unknown">a stated convention</Tag>
                        {/* RENDERED VERBATIM, NEVER SUMMARISED. Each sentence
                            names what the number substitutes for and why that
                            cannot be known — one cites a declined capability,
                            another a telemetry column that is NULL in Phase A.
                            Summarising turns a checkable statement into a shrug,
                            and the honesty is the only thing making these
                            constants defensible. */}
                        <p className="mt-1.5 text-caption max-w-prose leading-relaxed text-foreground-muted">
                          {t.stands_in_for}
                        </p>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}

      <p className="max-w-prose text-caption text-foreground-muted">
        Every number on this page is a stated convention. None is derived from any tenant&apos;s
        data, and each says what it stands in for — fitting them needs capabilities that do not
        exist.
      </p>
    </div>
  );
}
