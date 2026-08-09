import { PageHeader } from "@/components/shared/PageHeader";
import { RunHistory, type RunHistoryRow } from "@/components/synapse/RunHistory";
import {
  Column,
  Footnote,
  SubNav,
  SynapseDown,
} from "@/components/synapse/primitives";
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
// THE RENDERING MOVED TO components/synapse/RunHistory.tsx IN B2b, unchanged.
// The tenant page's Runs tab shows the same table for one client, and it used to
// draw it as plain rows with its own idea of what "completed" meant. One table
// deserves one rendering; this page calls the code it used to contain, so what it
// draws is the same by construction rather than by two files agreeing.
//
// GROUPED BY SLOT, WHICH IS HOW IT IS DISPATCHED, and the grouping went with it.
// The slot is the unit of work - one sweep, every provisioned monitor, once - so
// it is the unit of display, and each group carries the totals a row cannot.
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
// NO FILTERS. The mockup shows Tenant, Monitor, Outcome and a date range, and
// GET /runs accepts `limit` and nothing else - unlike GET /alerts, which does
// take state, analysis_id, tenant_id and store_id. Rendering controls that
// cannot filter would be four dead ones, so they wait for the endpoint.

const LIMIT = 100;

const SUBTITLE =
  "Every sweep, grouped by the day it covers. A day runs once however many times it is dispatched, " +
  "and a run that assessed nothing says why.";

export default async function RunsPage() {
  let runs: RunHistoryRow[];
  try {
    ({ runs } = await synapseGet<{ runs: RunHistoryRow[] }>(`/runs?limit=${LIMIT}`));
  } catch (error) {
    if (error instanceof SynapseUnavailable) {
      return (
        <div>
          <PageHeader title="Runs" subtitle={SUBTITLE} />
          <Column>
            <SubNav current="runs" />
            <SynapseDown message={error.message} />
          </Column>
        </div>
      );
    }
    throw error;
  }

  return (
    <div>
      <PageHeader title="Runs" subtitle={SUBTITLE} />

      <Column>
        <SubNav current="runs" />
        <section>
          {runs.length === 0 ? (
            <p className="text-body text-foreground-muted">
              Nothing has run yet. The orchestrator fires daily in each tenant&apos;s own timezone,
              and only for monitors that are enabled.
            </p>
          ) : (
            <RunHistory runs={runs} truncated={runs.length >= LIMIT} limit={LIMIT} />
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
