import { PageHeader } from "@/components/shared/PageHeader";
import {
  Column,
  Footnote,
  type Refusals,
  SectionHead,
  SynapseDown,
  Tag,
  type Tone,
  plural,
  reasonLabel,
} from "@/components/synapse/primitives";
import { ANALYSIS_NAMES } from "@/lib/synapse/names";
import { SynapseUnavailable, synapseGet } from "@/lib/synapse/server-client";

// NEVER PRERENDER THIS PAGE. It reads SYNAPSE_BFF_URL and the caller's session at
// request time; prerendering executes it during `next build`, where neither
// exists, and bakes the resulting error notice into static HTML that the
// container then serves for ever. That shipped once, see lib/synapse/server-client.ts.
//
// scripts/assert-dynamic-routes.mjs fails the build if this route comes out
// static, so the directive cannot be silently dropped.
export const dynamic = "force-dynamic";

// R6 - the runs log. The DENOMINATOR: what ran, for whom, on which day.
//
// WHY THIS SCREEN MATTERS MORE THAN IT LOOKS. A run that produced zero actions
// leaves no trace in synapse.actions, so without this table a tenant that has
// been analysed every day for a month and one that has never been analysed at
// all look identical. Absence cannot be read from a table of presences.
//
// GROUPED BY SLOT, WHICH IS HOW IT IS DISPATCHED. It was a flat five-column table
// where the day was the first cell of every row, so a reader counting what
// happened on Thursday counted rows by eye and had no total. The slot is the unit
// of work - one sweep, every provisioned monitor, once - so it is the unit of
// display, and each group can carry the totals a row cannot.
//
// THE SPEC'S "dispatches against that day" PANEL IS DELIBERATELY ABSENT.
// synapse.run holds ONE ROW PER SLOT - that is the whole point of the slot key,
// and it is why a redelivered dispatch is the same run rather than a second one.
// The "already done" lines the mockup showed live in Cloud Run execution history:
// a different source, needing the Run Admin API and an IAM grant on this
// service's identity, whose data ages out. A new external dependency for one
// decorative panel. Fabricating those lines from the run row would have been
// worse than not showing them.
//
// NO "scheduled - 03:00 IST" ON THE GROUP HEADER either, which the mockup had.
// synapse.run carries no timezone and no trigger source: the tenant's timezone
// lives on synapse.provision and is not on this payload, and nothing anywhere
// records whether a run came from the scheduler or a manual dispatch. Both halves
// of that line would have been invented.

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
  // migration 0005. null = the run never reached its plan; {} = it ran and
  // refused nothing; {..} = counts by reason.
  refusals: Refusals | undefined;
};

const LIMIT = 100;

const SUBTITLE =
  "Every sweep, grouped by the day it covers. A day runs once however many times it is dispatched, " +
  "and a run that assessed nothing says why.";

// 'satisfied' is engineering voice for "the run completed". The other three name real distinct
// states with no agreed plain-English equivalent, so they render as-is rather than invented.
function outcomeLabel(outcome: string | null): string {
  if (outcome === null) return "unfinished";
  return outcome === "satisfied" ? "completed" : outcome;
}

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

// What the run FOUND, in the run's own numbers and no others.
//
// NO "N series assessed", which the mockup put on every row. Nothing records how
// many series a run looked at: synapse.run holds actions_proposed,
// actions_appended and the refusal counts, and refusals only counts the series a
// monitor turned down. proposed + refused is not the denominator either, because
// a series that was assessed and found healthy is counted nowhere. The number
// does not exist, so the sentence does not claim it.
//
// PROPOSED IS THE HEADLINE, appended the correction. Appended can be lower than
// proposed with nothing wrong: a repeat of a finding already recorded for the
// same slot is suppressed by the idempotency index rather than duplicated.
function found(row: RunRow): string {
  const proposed = row.actions_proposed;
  const appended = row.actions_appended;
  if (proposed === null) return "no result recorded";
  if (proposed === 0) return "no alerts raised";
  const suppressed = appended === null ? null : proposed - appended;
  const head = `${plural(proposed, "alert")} raised`;
  return suppressed && suppressed > 0
    ? `${head}, ${suppressed} suppressed as a repeat`
    : head;
}

// One chip per stored reason, biggest first, ties broken on the key so the order
// is stable across renders. This is the whole breakdown rather than
// refusalSummary's dominant reason: a fleet table's status cell had room for one,
// a group row has room for all of them, and the reason a monitor stayed quiet is
// the question this screen is most often opened to answer.
function skipChips(refusals: Refusals): Array<[string, number]> {
  if (!refusals) return [];
  return Object.entries(refusals)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

type SlotGroup = {
  slot: string;
  runs: RunRow[];
  alerts: number;
  skipped: number;
  // True when this group sits at the end of a truncated response, so its totals
  // are a floor rather than a count. See the comment at the call site.
  partial: boolean;
};

// CONTIGUOUS GROUPING, not a Map, because the BFF already returns slot DESC and
// re-sorting here would be a second opinion about ordering. Runs for one slot
// therefore arrive adjacent, and a change in the value starts a group.
function groupBySlot(runs: RunRow[], truncated: boolean): SlotGroup[] {
  const groups: SlotGroup[] = [];
  for (const run of runs) {
    let group = groups[groups.length - 1];
    if (!group || group.slot !== run.slot) {
      group = { slot: run.slot, runs: [], alerts: 0, skipped: 0, partial: false };
      groups.push(group);
    }
    group.runs.push(run);
    group.alerts += run.actions_proposed ?? 0;
    group.skipped += skipChips(run.refusals ?? null).reduce((sum, [, n]) => sum + n, 0);
  }
  // ONLY THE LAST GROUP CAN BE SHORT. The response is ordered by slot, so a cap
  // cuts the oldest day in the middle and every group above it is whole. Saying
  // "3 runs" for a day whose fourth run fell past the limit would be the screen
  // asserting something it cannot see.
  const last = groups[groups.length - 1];
  if (truncated && last) last.partial = true;
  return groups;
}

// The wall-clock span of one sweep: first start to last finish. A SPAN, NOT A
// SUM - the runs overlap, so adding the per-run durations would report a number
// no clock ever showed. Omitted entirely while any run in the group is still
// open, because the span has not happened yet.
function sweepSpan(group: SlotGroup): string | null {
  if (group.runs.some((r) => !r.finished_at)) return null;
  const started = Math.min(...group.runs.map((r) => new Date(r.started_at).getTime()));
  const finished = Math.max(...group.runs.map((r) => new Date(r.finished_at!).getTime()));
  const ms = finished - started;
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

export default async function RunsPage() {
  let runs: RunRow[];
  try {
    ({ runs } = await synapseGet<{ runs: RunRow[] }>(`/runs?limit=${LIMIT}`));
  } catch (error) {
    if (error instanceof SynapseUnavailable) {
      return (
        <div>
          <PageHeader title="Runs" subtitle={SUBTITLE} />
          <Column>
            <SynapseDown message={error.message} />
          </Column>
        </div>
      );
    }
    throw error;
  }

  const groups = groupBySlot(runs, runs.length >= LIMIT);

  return (
    <div>
      <PageHeader title="Runs" subtitle={SUBTITLE} />

      <Column>
        <section>
          <SectionHead>Newest first</SectionHead>
          {groups.length === 0 ? (
            <p className="text-body text-foreground-muted">
              Nothing has run yet. The orchestrator fires daily in each tenant&apos;s own timezone,
              and only for monitors that are enabled.
            </p>
          ) : (
            <div className="space-y-4">
              {groups.map((group) => (
                <div key={group.slot} className="rounded-md border border-border">
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-border bg-surface-raised px-4 py-2.5">
                    <span className="text-body-strong font-mono">{group.slot}</span>
                    <span className="text-caption text-foreground-muted">
                      {plural(group.runs.length, "run")} · {group.alerts} raised ·{" "}
                      {group.skipped} skipped
                    </span>
                    {sweepSpan(group) ? (
                      <span className="text-micro ml-auto text-foreground-subtle">
                        {sweepSpan(group)}
                      </span>
                    ) : null}
                  </div>

                  {group.runs.map((run) => (
                    <div
                      key={run.run_id}
                      className="flex flex-wrap items-start gap-x-4 gap-y-2 border-b border-border px-4 py-3 last:border-b-0"
                    >
                      <div className="w-52 shrink-0">
                        <p className="text-body-strong">
                          {ANALYSIS_NAMES[run.analysis_id] ?? run.analysis_id}
                        </p>
                        <p className="text-caption text-foreground-muted">{run.tenant_name}</p>
                      </div>

                      <div className="shrink-0">
                        <Tag tone={run.outcome ? (OUTCOME_TONE[run.outcome] ?? "mute") : "unknown"}>
                          {outcomeLabel(run.outcome)}
                        </Tag>
                      </div>

                      <div className="min-w-0 flex-1">
                        <p className="text-caption text-foreground-muted">{found(run)}</p>
                        {/* THE STORED BREAKDOWN, not a hedge about it. Before
                            migration 0005 a quiet run and a run that could not
                            assess anything were the same row; these chips are the
                            recorded answer, so nothing here is inferred. Rendered
                            only when something was actually refused: "0 refused"
                            on every healthy row is noise. */}
                        {skipChips(run.refusals ?? null).length > 0 ? (
                          <div className="mt-1.5 flex flex-wrap gap-1.5">
                            {skipChips(run.refusals ?? null).map(([reason, n]) => (
                              <span
                                key={reason}
                                className="text-micro rounded-sm border border-border bg-surface px-2 py-0.5 font-mono text-foreground-subtle"
                              >
                                {reasonLabel(reason)} × {n}
                              </span>
                            ))}
                          </div>
                        ) : null}
                        {/* The absent map, said as absence. undefined means the
                            response predates the column or the run never reached
                            its plan; empty means it ran and refused nothing. Only
                            one of those is safe to render as silence. */}
                        {run.refusals === undefined && run.outcome !== null ? (
                          <p className="text-micro mt-1 text-foreground-subtle">
                            no refusal breakdown was recorded for this run
                          </p>
                        ) : null}
                      </div>

                      <div className="text-caption shrink-0 font-mono whitespace-nowrap text-foreground-subtle">
                        {took(run)}
                      </div>
                    </div>
                  ))}

                  {group.partial ? (
                    <p className="text-micro border-t border-border px-4 py-2 text-foreground-subtle">
                      This day is cut off by the {LIMIT}-run limit, so its totals are at least
                      these and may be higher.
                    </p>
                  ) : null}
                </div>
              ))}
            </div>
          )}

          <div className="mt-4">
            <Footnote>
              A repeat of an alert already recorded for the same day is suppressed rather than
              duplicated, so a run can raise nothing and still be working. An{" "}
              <span className="font-mono">unfinished</span> row is a run that was claimed and
              never completed; the next run for that day adopts and finishes it, which is why a
              crash does not lose a day.
            </Footnote>
          </div>
        </section>
      </Column>
    </div>
  );
}
