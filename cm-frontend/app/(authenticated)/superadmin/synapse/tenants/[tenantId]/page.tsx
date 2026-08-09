import { notFound } from "next/navigation";

import { PageHeader } from "@/components/shared/PageHeader";
import {
  AlertStateTag,
  Attention,
  Breadcrumb,
  Column,
  Footnote,
  type Refusals,
  Row,
  SectionHead,
  SilentModePill,
  Stat,
  StatStrip,
  SynapseDown,
  Tag,
  UnknownStateTag,
  asAlertState,
  daysSince,
  isOpen,
  plural,
  refusalSentence,
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
  // migration 0005. Restores what Phase A's item 5a wanted and could not have:
  // null = the last run never reached its plan; {} = it ran and refused nothing.
  refusals: Refusals | undefined;
};

// 5c. The tenant page listed alerts AGGREGATED PER MONITOR ("3 alerts raised") because
// no endpoint returned individual ones — synapse.actions appeared in the BFF only as
// count(*). /tenants/{id}/alerts returns them, so the section can list what was actually
// raised and each line can open.
type AlertRow = {
  event_id: string;
  as_of: string;
  declaration_id: string;
  quantity_at_stake: string | null;
  days_since_last_sale: number | null;
  days_of_cover: string | null;
  sku_id: string | null;
  product_name: string | null;
  store_name: string | null;
  lifecycle_verb: string | null;
  lifecycle_reason: string | null;
  lifecycle_snoozed_until: string | null;
  // Derived by the BFF, never here. Typed `string` because it crosses the wire;
  // asAlertState narrows it once at the render site.
  lifecycle_state: string;
};

const ALERTS_LIMIT = 50;

type TenantDetail = {
  tenant_id: string;
  name: string;
  products: number;
  stores: number;
  sales_seen: number;
  latest_sale: string | null;
  actions_recorded: number;
  // COUNTED BY THE SERVER, on the same construct as the fleet roster and the inbox chips.
  // This page used to count open rows out of its own LIMIT-50 alert list, which counted what
  // was DISPLAYED and called it a property of the tenant.
  open_alerts: number;
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
  refusals: Refusals | undefined;
};

// "Last ran 2026-08-07 · 12 series refused — sales data too old". The full
// sentence rather than the fleet table's terse chip: this is the screen where an
// operator asks why one client's monitor is quiet.
function monitorNote(state: AnalysisState): string {
  const ran = state.last_slot ? `Last ran ${state.last_slot}` : "Has not run yet";
  const refused = refusalSentence(state.refusals ?? null);
  return refused ? `${ran} · ${refused}` : ran;
}

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

  // DEGRADES RATHER THAN FAILS, matching the runs fetch below: the page is still worth
  // rendering without its alert list, and an exception here would take the whole tenant
  // view down over a section.
  let alerts: AlertRow[] = [];
  try {
    ({ alerts } = await synapseGet<{ alerts: AlertRow[] }>(
      `/tenants/${tenantId}/alerts?limit=${ALERTS_LIMIT}`,
    ));
  } catch (error) {
    if (!(error instanceof SynapseUnavailable)) throw error;
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
  const openAlerts = detail.open_alerts;

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
          {/* "OPEN" IS SAYABLE NOW. This read "alerts raised (all time)" because
              synapse.actions had no lifecycle column and "open" would have named a
              state the system could not represent. Migration 0006 gives it one, so
              the honest headline is the one an operator acts on.

              ACKNOWLEDGED COUNTS AS OPEN (see isOpen): acknowledging says somebody
              has seen it and left it standing, which is not the same as closing it.

              THE ALL-TIME COUNT IS KEPT ALONGSIDE, not replaced. It is the
              attribution denominator D1 exists to protect, and redefining the
              number under the same label would silently change what an old
              screenshot means. */}
          <Stat n={openAlerts} label={openAlerts === 1 ? "open alert" : "open alerts"} warn={openAlerts > 0} />
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
          {/* LISTS THE ALERTS THEMSELVES NOW, not a per-monitor count. The count was all
              the data allowed before /tenants/{id}/alerts existed; each line now opens the
              full story. Falls back to the aggregate ONLY when the alert fetch failed but
              the monitors say alerts exist — showing nothing there would claim a quiet
              client when the truth is a broken section. */}
          {alerts.length === 0 ? (
            alerting.length === 0 ? (
              <p className="text-body text-foreground-muted">
                No alerts from the most recent run of any monitor.
              </p>
            ) : (
              <p className="text-body text-foreground-muted">
                {plural(
                  alerting.reduce((n, a) => n + (a.actions_proposed ?? 0), 0),
                  "alert",
                )}{" "}
                raised, but the alert list could not be loaded.
              </p>
            )
          ) : (
            alerts.map((a) => {
              // NARROWED ONCE, HERE, at the wire boundary. Everything downstream is typed,
              // so a state this build does not know about renders as the word itself rather
              // than being filed under one of the four.
              const state = asAlertState(a.lifecycle_state);
              return (
              <Row
                key={a.event_id}
                // ATTENTION ONLY WHILE IT IS OPEN. A snoozed, acknowledged or dismissed
                // alert stays on the list, it is still a recorded finding, but it stops
                // shouting: all three are decisions, and open means "needs a decision".
                attention={state !== null && isOpen(state)}
                right={
                  state === null ? (
                    <UnknownStateTag state={a.lifecycle_state} />
                  ) : (
                    <AlertStateTag
                      state={state}
                      reason={a.lifecycle_reason}
                      snoozedUntil={a.lifecycle_snoozed_until}
                    />
                  )
                }
                title={
                  <a
                    className="text-primary underline-offset-2 hover:underline"
                    href={`/superadmin/synapse/tenants/${tenantId}/alerts/${a.event_id}`}
                  >
                    {a.product_name ?? a.sku_id ?? "Unknown product"}
                  </a>
                }
                meta={
                  <>
                    {a.store_name ? `${a.store_name} · ` : ""}Raised {a.as_of} by the{" "}
                    {ANALYSIS_NAMES[a.declaration_id] ?? a.declaration_id} monitor · not sent to
                    client (silent mode)
                    <span className="text-micro mt-1 block font-mono text-foreground-subtle">
                      {a.sku_id ?? "no SKU on this alert"}
                    </span>
                  </>
                }
              />
              );
            })
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
                  // WHY A MONITOR RAISED NOTHING, when the run says. Appended to the
                  // "last ran" line rather than given its own row: it is a property of
                  // that run, and Phase A deleted a standalone row here precisely
                  // because it described engineering backlog instead of the data.
                  note={monitorNote(state)}
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
