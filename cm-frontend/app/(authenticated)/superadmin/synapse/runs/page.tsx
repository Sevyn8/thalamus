import { PageHeader } from "@/components/shared/PageHeader";
import {
  Column,
  Footnote,
  MonoChip,
  Panel,
  PanelHeader,
  PanelNote,
  PanelRow,
  type Refusals,
  SynapseDown,
  Tag,
  plural,
  reasonLabel,
  runDetail,
  runOutcomeTag,
  skipChips,
  wallClock,
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
// NO "scheduled" ON THE GROUP HEADER, which the mockup had. Nothing anywhere
// records whether a run came from the scheduler or a manual dispatch, so the word
// would be invented.
//
// THE TIME BESIDE IT IS NOT INVENTED, and an earlier version of this comment was
// wrong to say it was. It claimed "synapse.run carries no timezone", which is
// false about the TABLE: synapse.run.timezone has existed since migration 0003,
// snapshotted per run by the orchestrator so a later provisioning change cannot
// rewrite what an old run is recorded as having done. It was true only about the
// PAYLOAD, because no query selected the column. Phase B1 projects it, so the
// clock times below are read in the zone the run itself recorded.
//
// NO FILTERS. The mockup shows Tenant, Monitor, Outcome and a date range, and
// GET /runs accepts `limit` and nothing else - unlike GET /alerts, which does
// take state, analysis_id, tenant_id and store_id. Rendering controls that
// cannot filter would be four dead ones, so they wait for the endpoint.

type RunRow = {
  run_id: string;
  tenant_id: string;
  tenant_name: string;
  analysis_id: string;
  slot: string;
  // The zone the slot was floored in, snapshotted onto the run. See wallClock.
  timezone: string;
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

function took(row: RunRow): string {
  if (!row.finished_at) return "still running";
  const ms = new Date(row.finished_at).getTime() - new Date(row.started_at).getTime();
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
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
    // COUNTS appended, NOT proposed, so the header agrees with the rows beneath it.
    // Each row's tag says "N alerts raised" from actions_appended; a header summing
    // actions_proposed would report a larger number on a day where the idempotency
    // index suppressed a repeat, and a total that disagrees with the rows it totals
    // reads as a bug even when both numbers are right.
    group.alerts += run.actions_appended ?? 0;
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

// When the sweep started, on the clock of whoever it ran for.
//
// ONLY WHEN THE WHOLE GROUP SHARES ONE ZONE. A slot groups every tenant's run for
// that day, and two tenants in different timezones produce one group with no
// single wall clock: "03:00" would be true for one of them and silently wrong for
// the other. Both tenants sit in Asia/Kolkata today, so this returns a time; the
// branch exists so that adding a tenant elsewhere drops the header time instead
// of starting to lie. Each ROW still shows its own start, which is always right.
function sweepStart(group: SlotGroup): { time: string; zone: string } | null {
  const zones = new Set(group.runs.map((run) => run.timezone));
  if (zones.size !== 1) return null;
  const earliest = group.runs.reduce((a, b) =>
    new Date(a.started_at).getTime() <= new Date(b.started_at).getTime() ? a : b,
  );
  return wallClock(earliest.started_at, earliest.timezone);
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
          {groups.length === 0 ? (
            <p className="text-body text-foreground-muted">
              Nothing has run yet. The orchestrator fires daily in each tenant&apos;s own timezone,
              and only for monitors that are enabled.
            </p>
          ) : (
            <div className="space-y-4">
              {groups.map((group) => {
                const started = sweepStart(group);
                const span = sweepSpan(group);
                return (
                  <Panel key={group.slot}>
                    <PanelHeader>
                      <span className="text-body-strong font-mono tabular-nums">{group.slot}</span>
                      <span className="text-caption text-foreground-muted tabular-nums">
                        {plural(group.runs.length, "run")} · {plural(group.alerts, "alert")} raised
                        · {group.skipped} series skipped
                      </span>
                      {started || span ? (
                        <span className="text-micro ml-auto font-mono tabular-nums text-foreground-subtle">
                          {[started ? `${started.time} ${started.zone}` : null, span]
                            .filter(Boolean)
                            .join(" · ")}
                        </span>
                      ) : null}
                    </PanelHeader>

                    {group.runs.map((run) => {
                      const tag = runOutcomeTag(run);
                      const detail = runDetail(run);
                      const skips = skipChips(run.refusals ?? null);
                      const at = wallClock(run.started_at, run.timezone, { seconds: true });
                      return (
                        <PanelRow key={run.run_id}>
                          <div className="w-52 shrink-0">
                            <p className="text-body-strong">
                              {ANALYSIS_NAMES[run.analysis_id] ?? run.analysis_id}
                            </p>
                            <p className="text-caption text-foreground-muted">{run.tenant_name}</p>
                          </div>

                          <div className="shrink-0">
                            {/* NO DOT. The mockups' status pill carries a border and
                                its tone, and the dot repeats the tone without adding
                                anything. Opted out per call site rather than by
                                forking the house chip. */}
                            <Tag tone={tag.tone} dot={false}>
                              {tag.label}
                            </Tag>
                          </div>

                          <div className="min-w-0 flex-1">
                            {detail ? (
                              <p className="text-caption text-foreground-muted tabular-nums">
                                {detail}
                              </p>
                            ) : null}
                            {/* THE STORED BREAKDOWN, not a hedge about it. Before
                                migration 0005 a quiet run and a run that could not
                                assess anything were the same row; these chips are the
                                recorded answer, so nothing here is inferred. Rendered
                                only when something was actually refused: "0 refused"
                                on every healthy row is noise. */}
                            {skips.length > 0 ? (
                              <div className={`flex flex-wrap gap-1.5 ${detail ? "mt-1.5" : ""}`}>
                                {skips.map(([reason, n]) => (
                                  <MonoChip key={reason}>
                                    skipped - {reasonLabel(reason)} × {n}
                                  </MonoChip>
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

                          {/* TIME AND DURATION, both. The mockup shows the clock time
                              and the group header shows the span; the duration is kept
                              beneath it because "when did this start" and "how long did
                              it take" are different questions and the row has room for
                              both. */}
                          <div className="shrink-0 text-right font-mono tabular-nums whitespace-nowrap">
                            {at ? (
                              <p className="text-caption text-foreground-muted">{at.time}</p>
                            ) : null}
                            <p className="text-micro text-foreground-subtle">{took(run)}</p>
                          </div>
                        </PanelRow>
                      );
                    })}

                    {group.partial ? (
                      <PanelNote>
                        This day is cut off by the {LIMIT}-run limit, so its totals are at least
                        these and may be higher.
                      </PanelNote>
                    ) : null}
                  </Panel>
                );
              })}
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
