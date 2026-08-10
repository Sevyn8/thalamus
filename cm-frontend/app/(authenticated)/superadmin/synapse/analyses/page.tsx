import { PageHeader } from "@/components/shared/PageHeader";
import {
  Column,
  Footnote,
  ItemCard,
  MonoChip,
  SubNav,
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
  // SERVED AND DELIBERATELY NOT RENDERED. stands_in_for is what the constant SUBSTITUTES FOR:
  // an argument aimed at whoever reviews the declaration, which analysis.py's __post_init__
  // refuses to let a constant ship without. The six values run to 1302 characters and name
  // PERCENTILE_CONT, _DECLINED, telemetry.connector_health and config.sources.schedule. It was
  // rendered under every threshold, which put a reviewer's note in front of an operator.
  // Kept on the type so it is visibly a choice not to draw it.
  stands_in_for: string | null;
  // What the number DOES, in one sentence. Guaranteed present by a coverage test in the BFF
  // (test_every_threshold_has_an_operator_description), so this never falls back to an id.
  description: string;
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
            <SubNav current="analyses" />
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
        <SubNav current="analyses" />
        {/* CARD PER ANALYSIS (B2), which is the mockup's treatment: a headed card whose body is
            a ruled contract grid. The card's own header carries the plain name, the machine id
            and the status pills, exactly as `.ahead` does.

            THE MOCKUP'S BODY HAS THREE COLUMNS AND THIS HAS TWO, because the third has no
            source. `Consumes · capabilities` is `requires`, which the BFF serves. The other two
            are `Emits · finding fields` and `Can refuse · closed vocabulary`, and GET /analyses
            returns neither: it serves analysis_id, name, version, requires, max_rung, thresholds
            and holdout_percent. The emitted fields live on the Finding dataclasses and the
            refusal vocabulary on each analysis's RefusalReason enum, and nothing projects either
            over the wire. Rendering them would mean hardcoding a copy of two Python enums into
            this file, which is the duplication that goes stale silently.

            THRESHOLDS TAKE THE THIRD COLUMN INSTEAD. They are the numbers this page already had
            and the mockup shows them as `.chip` mono tags on the tenant Monitors card, so the
            vocabulary is the mockups' own. The day /analyses serves emits and refusals, they are
            two more columns here and nothing else moves. */}
        <div className="space-y-4">
        {analyses.map((a) => (
          <ItemCard key={a.analysis_id}>
            {/* METADATA WITH ITS SUBJECT. The id, version, ceiling and holdout were
                split across a left block and a right-aligned cluster with the width
                of the monitor between them. */}
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border pb-3">
              <span className="text-subheading">{a.name}</span>
              <span className="text-caption font-mono text-foreground-subtle">
                {a.analysis_id}
              </span>
              <span className="text-caption ml-auto font-mono text-foreground-subtle">
                {a.version}
              </span>
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

            {/* COLUMN 1 OF THE MOCKUP'S GRID: what this analysis consumes. */}
            <div className="border-b border-border py-3">
              <h3 className="text-label text-foreground-subtle">Consumes</h3>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {a.requires.map((c) => (
                  <MonoChip key={c}>{c}</MonoChip>
                ))}
              </div>
              <p className="text-caption mt-2 text-foreground-muted">
                Reads {a.requires.map((c) => CAPABILITY_NAMES[c] ?? c).join(" and ")}.
              </p>
            </div>

            {/* TWO COLUMNS. The threshold name and its value are one fact; the
                explanation sits under them rather than as a third column. */}
            <h3 className="text-label mt-3 text-foreground-subtle">Thresholds</h3>
            <table className="w-full">
              <tbody>
                {a.thresholds.map((t) => (
                  <tr key={t.name} className="border-b border-border align-baseline last:border-b-0">
                    <td className="py-3 pr-4">
                      <p className="text-body font-mono">{t.name}</p>
                      {/* WHAT THE NUMBER DOES, not what it stands in for.
                          This rendered `stands_in_for` until B2b-2, and that field
                          is a REVIEWER's argument: analysis.py refuses to construct
                          an unfitted threshold without one, so it exists to make
                          somebody justify a constant. It reads like it, up to 1302
                          characters naming PERCENTILE_CONT, a declined capability
                          and two NULL telemetry columns. Correct where it is
                          declared, wrong on a screen an operator opens at 09:00.

                          The field is unchanged and still served; only the audience
                          is fixed. The "a convention" pill beside this already says
                          the number is a choice rather than a measurement, which is
                          the honest part; this says what the choice does. */}
                      <p className="text-caption mt-1 text-measure leading-relaxed text-foreground-subtle">
                        {t.description}
                      </p>
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
          </ItemCard>
        ))}
        </div>

        <Footnote>
          Every number on this page is a stated convention. None is derived from any tenant&apos;s
          data, and each says what it stands in for: fitting them needs capabilities that do not
          exist.
        </Footnote>
      </Column>
    </div>
  );
}
