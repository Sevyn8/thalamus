import { notFound } from "next/navigation";

import { PageHeader } from "@/components/shared/PageHeader";
import {
  Attention,
  Breadcrumb,
  Column,
  Footnote,
  Row,
  SectionHead,
  SilentModePill,
  Stat,
  StatStrip,
  SynapseDown,
  Tag,
  daysSince,
  plural,
} from "@/components/synapse/primitives";
import { ANALYSIS_NAMES, MONITOR_DESCRIPTIONS } from "@/lib/synapse/names";
import { SynapseUnavailable, synapseGet } from "@/lib/synapse/server-client";

// NEVER PRERENDER THIS PAGE. It reads SYNAPSE_BFF_URL and the caller's session at
// request time; prerendering executes it during `next build`, where neither
// exists, and bakes the resulting error notice into static HTML that the
// container then serves for ever. That shipped once — see lib/synapse/server-client.ts.
//
// scripts/assert-dynamic-routes.mjs fails the build if this route comes out
// static, so the directive cannot be silently dropped.
export const dynamic = "force-dynamic";

// R2 — one tenant. Two analyses, one producing and one correctly refusing, with
// the refusal explained rather than shown as a blank.

type AnalysisState = {
  analysis_id: string;
  cadence: string;
  rung: string;
  timezone: string;
  enabled_at: string;
  last_slot: string | null;
  last_outcome: string | null;
  actions_proposed: number | null;
  actions_appended: number | null;
  detail: string | null;
};

type TenantDetail = {
  tenant_id: string;
  name: string;
  products: number;
  stores: number;
  sales_seen: number;
  latest_sale: string | null;
  actions_recorded: number;
  analyses: AnalysisState[];
};

// The strictest freshness threshold any monitor declares — same constant, same reason, as the
// fleet page. A tenant staler than this has every rate-based monitor finding nothing.
const STALE_AFTER_DAYS = 3;

// OUTCOMES ARE RENDERED, NOT TRANSLATED, with one exception. 'satisfied' is engineering voice
// for "the run completed", so it reads "completed". 'blocked', 'undeclared' and 'failed' are
// rendered as-is and muted: each names a real distinct state, none has an agreed plain-English
// equivalent, and inventing one would put a word on screen that no log or run row contains.
function outcomeLabel(outcome: string | null): string {
  if (outcome === null) return "unfinished";
  return outcome === "satisfied" ? "completed" : outcome;
}

// The BFF bounds this at _MAX_ROWS = 500 and floors it at 1. Asking for the maximum is now a
// per-client maximum rather than a share of a fleet-wide one.
const RUNS_LIMIT = 500;

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

export default async function TenantPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = await params;

  let detail: TenantDetail;
  try {
    detail = await synapseGet<TenantDetail>(`/tenants/${tenantId}`);
  } catch (error) {
    if (error instanceof SynapseUnavailable) {
      // A 404 from the BFF means the id is not in the tenant mirror at all — a
      // different thing from a real tenant with nothing on, and the BFF refuses
      // to blur them by returning an empty shell.
      if (error.message.includes("404")) notFound();
      return (
        <div>
          <PageHeader title="Synapse" subtitle="One tenant" />
          <Column>
            <SynapseDown message={error.message} />
          </Column>
        </div>
      );
    }
    throw error;
  }

  // TENANT-SCOPED, filtered in SQL. This used to fetch the fleet-wide /runs at its maximum limit
  // and filter client-side on tenant_id, which silently truncated: another client's activity
  // could push this one's older runs past the cap, and the page could not tell "no history" from
  // "history fell off the end". The endpoint filters in the query, so the cap is this client's.
  let tenantRuns: RunRow[] = [];
  try {
    ({ runs: tenantRuns } = await synapseGet<{ runs: RunRow[] }>(
      `/tenants/${tenantId}/runs?limit=${RUNS_LIMIT}`,
    ));
  } catch (error) {
    // A failed run-history read must not blank the whole page: the sections above it are the
    // ones an operator came for. Rendered as an empty history rather than an error.
    if (!(error instanceof SynapseUnavailable)) throw error;
  }

  const staleDays = daysSince(detail.latest_sale);
  const isStale = staleDays === null || staleDays > STALE_AFTER_DAYS;
  const alerting = detail.analyses.filter((a) => (a.actions_proposed ?? 0) > 0);

  return (
    <div>
      <PageHeader
        title={detail.name}
        subtitle="Monitors watch this client's sales data and raise alerts here. Nothing is sent to the client."
        rightSlot={<SilentModePill />}
      />

      <Column>
        <Breadcrumb tenant={detail.name} />

        {isStale && (
          <Attention
            title={
              staleDays === null
                ? `${detail.name} has never sent a sale`
                : `${detail.name}'s sales data is ${plural(staleDays, "day")} stale`
            }
            detail={
              detail.latest_sale === null
                ? "No sale has ever been ingested. Rate-based monitors will find nothing until fresh data arrives."
                : `Last sale ingested ${detail.latest_sale}. Rate-based monitors will find nothing until fresh data arrives.`
            }
          />
        )}

        <StatStrip>
          <Stat n={detail.products} label={detail.products === 1 ? "product watched" : "products watched"} />
          <Stat n={detail.sales_seen} label={detail.sales_seen === 1 ? "sale ingested" : "sales ingested"} />
          <Stat n={detail.latest_sale ?? "—"} label="last sale" warn={isStale} />
          {/* "Alerts raised", never "open": synapse.actions has no lifecycle column. */}
          <Stat
            n={detail.actions_recorded}
            label={
              detail.actions_recorded === 1
                ? "alert raised (all time)"
                : "alerts raised (all time)"
            }
          />
        </StatStrip>

        <section>
          <SectionHead>Latest alerts</SectionHead>
          {alerting.length === 0 ? (
            <p className="text-body text-foreground-muted">
              No alerts from the most recent run of any monitor.
            </p>
          ) : (
            alerting.map((state) => (
              <Row
                key={state.analysis_id}
                attention
                // HEADLINED ON actions_proposed, NOT actions_appended. Appended can be 0 while
                // an alert genuinely exists: the idempotency index suppresses a repeat of the
                // same slot, so a real finding that was already recorded yesterday appends
                // nothing today. Proposed is what the monitor found.
                title={`${plural(state.actions_proposed ?? 0, "alert")} raised`}
                meta={
                  <>
                    {state.last_slot ? `Raised ${state.last_slot} ` : ""}by the{" "}
                    {ANALYSIS_NAMES[state.analysis_id] ?? state.analysis_id} monitor · not sent to
                    client (silent mode)
                  </>
                }
              />
            ))
          )}
        </section>

        <section>
          <SectionHead>Monitors</SectionHead>
          {detail.analyses.length === 0 ? (
            <p className="text-body text-foreground-muted">
              No monitors are enabled for this client yet.
            </p>
          ) : (
            detail.analyses.map((state) => {
              const raised = state.actions_proposed ?? 0;
              return (
                <Row
                  key={state.analysis_id}
                  title={ANALYSIS_NAMES[state.analysis_id] ?? state.analysis_id}
                  meta={
                    <>
                      {MONITOR_DESCRIPTIONS[state.analysis_id] ?? null}
                      {/* Config metadata, demoted. The rung is deliberately absent: the mode is
                          stated once by the pill in the header, and "shadow" is an internal name. */}
                      <span className="text-micro mt-1 block font-mono text-foreground-subtle">
                        {state.analysis_id} · {state.cadence} · {state.timezone}
                      </span>
                    </>
                  }
                  right={
                    <Tag tone={raised > 0 ? "unknown" : "mute"}>
                      {raised > 0 ? plural(raised, "alert") : "No alerts last run"}
                    </Tag>
                  }
                  note={state.last_slot ? `Last ran ${state.last_slot}` : "Has not run yet"}
                />
              );
            })
          )}
        </section>

        <section>
          <SectionHead>Run history</SectionHead>
          {tenantRuns.length === 0 ? (
            <p className="text-body text-foreground-muted">No runs recorded for this client yet.</p>
          ) : (
            tenantRuns.map((run) => (
              <Row
                key={run.run_id}
                title={ANALYSIS_NAMES[run.analysis_id] ?? run.analysis_id}
                meta={
                  <>
                    {run.slot} · {outcomeLabel(run.outcome)} ·{" "}
                    {plural(run.actions_proposed ?? 0, "alert")} raised
                  </>
                }
              />
            ))
          )}
        </section>

        <Footnote>
          Duplicate alerts for the same product are suppressed. Monitors re-check automatically
          when fresh data arrives.
        </Footnote>
      </Column>
    </div>
  );
}
