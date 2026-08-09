import { notFound } from "next/navigation";

import { PageHeader } from "@/components/shared/PageHeader";
import { RunHistory, type RunHistoryRow } from "@/components/synapse/RunHistory";
import {
  AlertStateTag,
  Attention,
  Breadcrumb,
  Column,
  Fact,
  Facts,
  Footnote,
  MonoChip,
  type Refusals,
  Row,
  SectionHead,
  SilentModePill,
  Stat,
  StatStrip,
  SynapseDown,
  Tabs,
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

// outcomeLabel WAS HERE AND IS DELETED. It rendered 'satisfied' as "completed" for this page's
// own flat run list, which is precisely the uniform label B1 replaced on the fleet page: a run
// that assessed nothing and a run that raised six alerts both read "completed". The Runs tab now
// calls RunHistory, whose outcome ladder derives what the run actually came to, so a second
// vocabulary for the same column no longer exists here.

// The BFF bounds this at _MAX_ROWS = 500 and floors it at 1. Asking for the maximum is now a
// per-client maximum rather than a share of a fleet-wide one.
const RUNS_LIMIT = 500;

// THE SAME SHAPE THE FLEET RUNS PAGE READS, imported rather than restated. This file used to
// declare its own narrower RunRow and draw plain rows from it; the Runs tab now calls the one
// RunHistory component, so a second description of the same table would only be a way to
// disagree with it.
type RunRow = RunHistoryRow;

// THRESHOLDS COME FROM /analyses, which is the registry rather than anything per-tenant. The
// Monitors tab shows what each monitor's numbers ARE; synapse.actions freezes the values in
// force at detection onto each action, so this is the current declaration and is labelled as
// such rather than as what produced any particular alert.
type ThresholdView = {
  name: string;
  days: number;
  fitted: boolean;
  stands_in_for: string | null;
};

type AnalysisCatalogRow = {
  analysis_id: string;
  name: string;
  version: string;
  requires: string[];
  max_rung: string;
  thresholds: ThresholdView[];
  holdout_percent: number | null;
};

// THE FIVE TABS, and what each is allowed to claim.
//
// ?tab= ON ONE ROUTE rather than five nested routes. One route means one set of fetches and one
// entry in MUST_BE_DYNAMIC; five would mean four more of each, and four more chances for one to
// be added without its guard. The inbox already keeps its filter state in the query string for
// the same reason, and a tab stays linkable and survives a refresh.
const TABS = ["overview", "monitors", "alerts", "runs", "data"] as const;
type TabKey = (typeof TABS)[number];

function asTab(raw: string | undefined): TabKey {
  return TABS.includes(raw as TabKey) ? (raw as TabKey) : "overview";
}

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
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<{ tab?: string }>;
}) {
  const { tenantId } = await params;
  const tab = asTab((await searchParams).tab);

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

  // THE DECLARATIONS, for the Monitors tab's thresholds. Degrades to an empty catalogue like
  // every other secondary fetch here: the monitor rows are worth showing without their numbers,
  // and a registry read failing must not blank a page about one client's data.
  let catalogue: AnalysisCatalogRow[] = [];
  try {
    ({ analyses: catalogue } = await synapseGet<{ analyses: AnalysisCatalogRow[] }>("/analyses"));
  } catch (error) {
    if (!(error instanceof SynapseUnavailable)) throw error;
  }
  const thresholdsFor = new Map(catalogue.map((a) => [a.analysis_id, a.thresholds]));

  const staleDays = daysSince(detail.latest_sale);
  const isStale = staleDays === null || staleDays > STALE_AFTER_DAYS;
  const alerting = detail.analyses.filter((a) => (a.actions_proposed ?? 0) > 0);
  const openAlerts = detail.open_alerts;

  const tabHref = (key: TabKey) =>
    key === "overview"
      ? `/superadmin/synapse/tenants/${tenantId}`
      : `/superadmin/synapse/tenants/${tenantId}?tab=${key}`;

  // THE COUNT ON THE ALERTS TAB IS THE SERVER'S open_alerts, not alerts.length. The list is
  // capped at ALERTS_LIMIT and the tab makes a claim about the CLIENT, which is the distinction
  // B2a spent a whole slice separating. No other tab carries a count, because no other number
  // here is a property of the tenant rather than of the page.
  const tabs = [
    { key: "overview", label: "Overview", href: tabHref("overview") },
    { key: "monitors", label: "Monitors", href: tabHref("monitors") },
    { key: "alerts", label: "Alerts", href: tabHref("alerts"), count: openAlerts },
    { key: "runs", label: "Runs", href: tabHref("runs") },
    { key: "data", label: "Data", href: tabHref("data") },
  ];

  return (
    <div>
      <PageHeader
        title={detail.name}
        subtitle="Monitors watch this client's sales data and raise alerts here. Nothing is sent to the client."
        rightSlot={<SilentModePill />}
      />

      <Column>
        <Breadcrumb tenant={detail.name} />

        <Tabs tabs={tabs} current={tab} />

        {tab === "overview" && isStale && (
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

        {tab === "overview" && (
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
        )}

        {tab === "alerts" && (
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

          {/* MOVED HERE FROM THE FOOT OF THE PAGE, unchanged. It explains the alert
              list and nothing else, so under tabs it belongs with what it explains. */}
          <div className="mt-4">
            <Footnote>
              Duplicate alerts for the same product are suppressed. Monitors re-check
              automatically when fresh data arrives.
            </Footnote>
          </div>
        </section>
        )}

        {tab === "monitors" && (
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
                      {/* THE DECLARED NUMBERS, from /analyses. THE CURRENT declaration, not
                          the one that produced any particular alert: synapse.actions freezes
                          the thresholds in force at detection onto each action, which is why
                          the alert detail page shows its own frozen copy and this does not
                          claim to be it. Absent entirely when the registry read failed,
                          rather than rendered as an empty row implying no thresholds. */}
                      {(thresholdsFor.get(state.analysis_id) ?? []).length > 0 ? (
                        <span className="mt-1.5 flex flex-wrap gap-1.5">
                          {(thresholdsFor.get(state.analysis_id) ?? []).map((t) => (
                            <MonoChip key={t.name}>
                              {t.name} {t.days}d
                            </MonoChip>
                          ))}
                        </span>
                      ) : null}
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

          {/* NO ENABLE BUTTONS, and their absence is the slice boundary rather than an
              oversight. The mockup's Monitors tab is also the proposed provisioning surface
              (5e): Enable and Configure would write synapse.provision through a scoped role.
              Nothing here writes anything, so rendering a button that does nothing would be a
              dead control, and rendering one that writes would be a slice nobody approved. */}
          <div className="mt-4">
            <Footnote>
              Monitors are enabled in the repository, not here. Thresholds shown are the current
              declaration; each alert carries its own frozen copy of the numbers in force when it
              was raised.
            </Footnote>
          </div>
        </section>
        )}

        {tab === "runs" && (
        <section>
          <SectionHead>Run history</SectionHead>
          {/* THE SAME COMPONENT THE FLEET RUNS PAGE USES. This was a flat list of rows
              carrying slot, outcome and a raised count, which was a second rendering of
              synapse.run with its own vocabulary: it said "completed" for every satisfied
              run, including ones that assessed nothing, which is exactly the uniform green
              pill B1 removed from the fleet page. One table, one rendering.

              showTenant is off because every row here is the same client, and repeating the
              name down the column pushes the monitor off its own line. */}
          {tenantRuns.length === 0 ? (
            <p className="text-body text-foreground-muted">No runs recorded for this client yet.</p>
          ) : (
            <RunHistory
              runs={tenantRuns}
              truncated={tenantRuns.length >= RUNS_LIMIT}
              limit={RUNS_LIMIT}
              showTenant={false}
            />
          )}
        </section>
        )}

        {tab === "data" && (
        <section>
          <SectionHead>Data</SectionHead>
          {/* WHAT THIS CLIENT HAS SENT, which is the question the other four tabs keep
              running into. Every figure is one the BFF already serves on /tenants/{id}:
              nothing here is derived, and nothing the mockup showed but the endpoint does
              not carry appears at all. */}
          <Facts>
            <Fact
              label="Last sale ingested"
              value={detail.latest_sale ?? "never"}
              note={
                detail.latest_sale === null
                  ? "no sale has ever arrived"
                  : staleDays === null
                    ? undefined
                    : `${plural(staleDays, "day")} ago`
              }
            />
            <Fact label="Sales ingested" value={detail.sales_seen.toLocaleString()} />
            <Fact label="Products watched" value={detail.products.toLocaleString()} />
            <Fact label="Stores" value={detail.stores.toLocaleString()} />
            <Fact
              label="Alerts recorded"
              value={detail.actions_recorded.toLocaleString()}
              note="all time"
            />
          </Facts>

          <div className="mt-4">
            <Footnote>
              Freshness is judged against the strictest window any monitor declares, currently{" "}
              {plural(STALE_AFTER_DAYS, "day")}. A client staler than that has every rate-based
              monitor finding nothing, and the run history says so per run rather than leaving it
              to be inferred from an empty alert list.
            </Footnote>
          </div>
        </section>
        )}
      </Column>
    </div>
  );
}
