import { PageHeader } from "@/components/shared/PageHeader";
import {
  Column,
  Footnote,
  SectionHead,
  SynapseDown,
  Tag,
  type Tone,
} from "@/components/synapse/primitives";
import { ANALYSIS_NAMES } from "@/lib/synapse/names";
import { SynapseUnavailable, synapseGet } from "@/lib/synapse/server-client";

// NEVER PRERENDER THIS PAGE. It reads SYNAPSE_BFF_URL and the caller's session at
// request time; prerendering executes it during `next build`, where neither
// exists, and bakes the resulting error notice into static HTML that the
// container then serves for ever. That shipped once — see lib/synapse/server-client.ts.
//
// scripts/assert-dynamic-routes.mjs fails the build if this route comes out
// static, so the directive cannot be silently dropped.
export const dynamic = "force-dynamic";

// R6 — the runs log. The DENOMINATOR: what ran, for whom, on which day.
//
// WHY THIS SCREEN MATTERS MORE THAN IT LOOKS. A run that produced zero actions
// leaves no trace in synapse.actions, so without this table a tenant that has
// been analysed every day for a month and one that has never been analysed at
// all look identical. Absence cannot be read from a table of presences.
//
// THE SPEC'S "dispatches against that day" PANEL IS DELIBERATELY ABSENT.
// synapse.run holds ONE ROW PER SLOT — that is the whole point of the slot key,
// and it is why a redelivered dispatch is the same run rather than a second one.
// The "already done" lines the mockup showed live in Cloud Run execution history:
// a different source, needing the Run Admin API and an IAM grant on this
// service's identity, whose data ages out. A new external dependency for one
// decorative panel. Fabricating those lines from the run row would have been
// worse than not showing them.

type RunRow = {
  run_id: string;
  tenant_id: string;
  tenant_name: string;
  analysis_id: string;
  slot: string;
  outcome: string | null;
  actions_proposed: number | null;
  actions_appended: number | null;
  started_at: string;
  finished_at: string | null;
};

const OUTCOME_TONE: Record<string, Tone> = {
  satisfied: "good",
  blocked: "unknown",
  undeclared: "unknown",
  failed: "stop",
};

function took(row: RunRow): string {
  if (!row.finished_at) return "still running";
  const ms = new Date(row.finished_at).getTime() - new Date(row.started_at).getTime();
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

export default async function RunsPage() {
  let runs: RunRow[];
  try {
    ({ runs } = await synapseGet<{ runs: RunRow[] }>("/runs"));
  } catch (error) {
    if (error instanceof SynapseUnavailable) {
      return (
        <div>
          <PageHeader title="Runs" subtitle="What ran, and what it found." />
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
        title="Runs"
        subtitle="One row per tenant, analysis and day. A day runs once however many times it is dispatched."
      />

      <Column>
        <section>
          <SectionHead>Newest first</SectionHead>
          {runs.length === 0 ? (
            <p className="text-body text-foreground-muted">
              Nothing has run yet. The orchestrator fires daily in each tenant&apos;s own timezone,
              and only for provisioned analyses.
            </p>
          ) : (
            /* SEVEN COLUMNS BECAME FIVE. At 840px seven gave every column ~120px
               and split the two action counts — which are one fact — across two
               headers a reader had to look up. Tenant and analysis are now stacked
               as one subject, and proposed/appended read as the pair they are. */
            <table className="w-full">
              <thead>
                <tr className="border-b border-border text-left">
                  <th className="text-label pb-2 pr-3 font-normal text-foreground-subtle">Day</th>
                  <th className="text-label pb-2 pr-3 font-normal text-foreground-subtle">Run</th>
                  <th className="text-label pb-2 pr-3 font-normal text-foreground-subtle">
                    Outcome
                  </th>
                  <th className="text-label pb-2 pr-3 text-right font-normal text-foreground-subtle">
                    Actions
                  </th>
                  <th className="text-label pb-2 text-right font-normal text-foreground-subtle">
                    Took
                  </th>
                </tr>
              </thead>
              <tbody>
                {runs.map((row) => (
                  <tr key={row.run_id} className="border-b border-border align-top last:border-b-0">
                    <td className="text-caption py-3 pr-3 font-mono whitespace-nowrap">
                      {row.slot}
                    </td>
                    <td className="py-3 pr-3">
                      <p className="text-body">{row.tenant_name}</p>
                      <p className="text-caption font-mono text-foreground-muted">
                        {ANALYSIS_NAMES[row.analysis_id] ?? row.analysis_id} · {row.analysis_id}
                      </p>
                    </td>
                    <td className="py-3 pr-3">
                      <Tag tone={row.outcome ? (OUTCOME_TONE[row.outcome] ?? "mute") : "unknown"}>
                        {row.outcome ?? "unfinished"}
                      </Tag>
                    </td>
                    <td className="text-caption py-3 pr-3 text-right font-mono whitespace-nowrap">
                      {row.actions_proposed ?? "—"} → {row.actions_appended ?? "—"}
                    </td>
                    <td className="text-caption py-3 text-right font-mono whitespace-nowrap">
                      {took(row)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="mt-3">
            <Footnote>
              <span className="font-mono">Actions</span> reads proposed → appended; appended is
              lower when a repeat of the same slot was suppressed by the idempotency index rather
              than duplicated. An <span className="font-mono">unfinished</span> row is a run that
              was claimed and never completed — a crashed sweep. The next dispatch for that slot
              adopts and finishes it rather than skipping, which is why a crash does not lose a day.
            </Footnote>
          </div>
        </section>
      </Column>
    </div>
  );
}
