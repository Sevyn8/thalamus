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
  ItemCard,
  MonoChip,
  Panel,
  PanelRow,
  type Refusals,
  SectionHead,
  SilentModePill,
  StatCard,
  StatCards,
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

import { EnableMonitor } from "./EnableMonitor";

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

// THE THIRD STATE (slice 5e). A pair that WAS provisioned and is now switched off.
//
// WITHOUT THIS THE ENABLE CONTROL IS A LIE. The BFF's active-monitor query filters
// `disabled_at IS NULL`, so before 5e a disabled pair simply did not appear and that
// was correct on a read-only screen. The moment an Enable control exists, an absent
// pair reads as "never provisioned" and the console offers to enable it; the insert
// is then refused by the primary key, and the BFF can only say "a row already
// existed" because the write credential cannot read the table to see whether that row
// is active or switched off. A control that offers an action the database will refuse,
// for a reason the page had the data to explain first, is worse than a dead one.
//
// So the BFF returns both halves of the partition and this tab renders three states.
type DisabledAnalysis = {
  analysis_id: string;
  enabled_at: string;
  disabled_at: string;
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
  disabled_analyses: DisabledAnalysis[];
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

  // THE TIMEZONE LIST, FROM THE BFF (5e timezone fix). Fetched here rather than derived
  // in the client component, because it is the intersection of what the BFF's own
  // zoneinfo and the Postgres it writes to both accept, and no browser can compute that.
  // The 5e picker read Intl.supportedValuesOf, which offered Asia/Calcutta, omitted
  // Asia/Kolkata, and made the control unable to emit the only value in production use.
  //
  // DEGRADES TO AN EMPTY LIST like every other secondary fetch on this page, and the
  // consequence is deliberate: with no list there is no Enable control at all. An Enable
  // button over an empty select is a dead control, and this page's whole rule is that a
  // control either does something or is not rendered.
  let zones: string[] = [];
  let zoneSource = "";
  try {
    const served = await synapseGet<{ timezones: string[]; source: string }>("/timezones");
    zones = served.timezones;
    zoneSource = served.source;
  } catch (error) {
    if (!(error instanceof SynapseUnavailable)) throw error;
  }

  // THE THREE ENABLEMENT STATES, PARTITIONED HERE ONCE (slice 5e).
  //
  //   active            detail.analyses            renders as today, no control
  //   disabled          detail.disabled_analyses   renders as disabled, NO control
  //   never provisioned the rest of the catalogue  renders with the Enable control
  //
  // DERIVED FROM THE CATALOGUE, NOT FROM A LIST OF NAMES. `catalogue` is /analyses,
  // which is synapse.registry's declared_analysis_ids() served as objects. An
  // analysis that exists in the registry is exactly one that can be provisioned
  // without breaking the sweep, so the available list cannot offer an id the
  // orchestrator would refuse. If the registry read failed, `catalogue` is empty and
  // nothing is offered, which is the correct degradation: no controls beats controls
  // built from a list we could not load.
  const enabledIds = new Set(detail.analyses.map((a) => a.analysis_id));
  const disabledById = new Map(detail.disabled_analyses.map((a) => [a.analysis_id, a]));
  const available = catalogue.filter(
    (a) => !enabledIds.has(a.analysis_id) && !disabledById.has(a.analysis_id),
  );

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

        {/* STAT CARDS (B3). This tab kept the inline strip through B2 because no mockup defines
            a tenant stat treatment, and the result was one untreated tab inside a page whose
            other four are cards, a table and panels. Stat cards are this system's treatment for
            stats, so a stat surface gets them; choosing an established treatment is not the
            uniformity error, which was making every page look like runs.

            FIVE COLUMNS, because there are five figures and a four-column grid would leave the
            fifth dangling on its own row. Dropping one would be content. */}
        {tab === "overview" && (
        <StatCards columns={5}>
          <StatCard value={detail.products} label={detail.products === 1 ? "product watched" : "products watched"} />
          <StatCard value={detail.sales_seen} label={detail.sales_seen === 1 ? "sale ingested" : "sales ingested"} />
          {/* "never" RATHER THAN A DASH. latest_sale is null only when no sale has ever
              been ingested for this client, which is a fact worth stating; a dash makes
              the reader work out whether it means none, unknown, or not loaded. There is
              no zero case for a date, so one word covers it. */}
          <StatCard value={detail.latest_sale ?? "never"} label="last sale" warn={isStale} />
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
          <StatCard value={openAlerts} label={openAlerts === 1 ? "open alert" : "open alerts"} warn={openAlerts > 0} />
          <StatCard
            value={detail.actions_recorded}
            label={
              detail.actions_recorded === 1
                ? "alert raised (all time)"
                : "alerts raised (all time)"
            }
          />
        </StatCards>
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
            <ItemCard>
              {alerting.length === 0 ? (
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
              )}
            </ItemCard>
          ) : (
            /* ONE CARD, ROWS INSIDE IT, the same treatment as the fleet inbox so the two alert
               lists read as one thing seen at two scopes. */
            <Panel>
              {alerts.map((a) => {
                // NARROWED ONCE, HERE, at the wire boundary. Everything downstream is typed,
                // so a state this build does not know about renders as the word itself rather
                // than being filed under one of the four.
                const state = asAlertState(a.lifecycle_state);
                // ATTENTION ONLY WHILE IT IS OPEN. A snoozed, acknowledged or dismissed
                // alert stays on the list, it is still a recorded finding, but it stops
                // shouting: all three are decisions, and open means "needs a decision".
                const attention = state !== null && isOpen(state);
                return (
                  <PanelRow key={a.event_id}>
                    <div className="min-w-0 flex-1">
                      <p
                        className={
                          attention ? "text-body-strong text-warning" : "text-body-strong"
                        }
                      >
                        <a
                          className="text-primary underline-offset-2 hover:underline"
                          href={`/superadmin/synapse/tenants/${tenantId}/alerts/${a.event_id}`}
                        >
                          {a.product_name ?? a.sku_id ?? "Unknown product"}
                        </a>
                      </p>
                      <p className="text-caption mt-0.5 text-foreground-muted">
                        {a.store_name ? `${a.store_name} · ` : ""}Raised {a.as_of} by the{" "}
                        {ANALYSIS_NAMES[a.declaration_id] ?? a.declaration_id} monitor · not sent
                        to client (silent mode)
                      </p>
                      <p className="text-micro mt-1 font-mono text-foreground-subtle">
                        {a.sku_id ?? "no SKU on this alert"}
                      </p>
                    </div>
                    <div className="shrink-0 text-right">
                      {state === null ? (
                        <UnknownStateTag state={a.lifecycle_state} />
                      ) : (
                        <AlertStateTag
                          state={state}
                          reason={a.lifecycle_reason}
                          snoozedUntil={a.lifecycle_snoozed_until}
                        />
                      )}
                    </div>
                  </PanelRow>
                );
              })}
            </Panel>
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
            <ItemCard>
              <p className="text-body text-foreground-muted">
                No monitors are enabled for this client yet.
              </p>
            </ItemCard>
          ) : (
            /* CARD PER ITEM (B2), the mockups' fourth treatment and the right one here: each
               monitor carries a BLOCK of facts, its description, its machine id, its declared
               thresholds and a stats rail, and ruled rows would put all of that between two
               hairlines and read as one undifferentiated list. */
            <div className="space-y-3">
              {detail.analyses.map((state) => {
              // READS actions_appended, NOT actions_proposed, AND THE DIFFERENCE IS A
              // CROSS-TAB DEFECT RATHER THAN A PREFERENCE. The Runs tab, one tab over,
              // renders the same run through runOutcomeTag, which counts appended. While
              // this counted proposed the two tabs disagreed about the SAME RUN on any day
              // the idempotency index suppressed a repeat: 1 proposed, 0 recorded, and one
              // screen saying "1 alert" beside another saying "no new alerts". That is the
              // cross-surface disagreement B2a spent a slice removing, and it came back in
              // B2b-1 through a label nobody read as a claim. Appended is what was actually
              // recorded, which is the only number an operator can go and look at.
              //
              // LABELLED "raised last run", NEVER BARE. It read "6 alerts" in an AMBER tag on
              // a page whose stat strip says "open alerts", so every signal said "6 open" while
              // the number meant "6 recorded by the most recent run". Proposed or appended,
              // neither says whether any is still open: open is a lifecycle question and
              // TenantDetail.open_alerts is the only thing that answers it. Muted for the same
              // reason, since a past raise is not something needing attention.
              const raised = state.actions_appended ?? 0;
              return (
                  <ItemCard key={state.analysis_id}>
                    <div className="flex flex-wrap items-start gap-4">
                      <div className="min-w-0 flex-1">
                        {/* THE MOCKUP'S `.mtop`: the plain name with its machine id beside it.
                            The id moved UP out of the metadata line to sit with the name, which
                            is where both the tenant-monitors and analyses mockups put it.

                            NO PER-CARD "silent mode" PILL, which the mockup draws on every
                            monitor. The mode is said ONCE per screen, in the header, and that is
                            a standing decision this console already made twice: SilentModePill's
                            own comment says so, and the alerts inbox refuses the mockup's per-row
                            copy of the same sentence for the same reason. */}
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-subheading">
                            {ANALYSIS_NAMES[state.analysis_id] ?? state.analysis_id}
                          </span>
                          <span className="text-micro font-mono text-foreground-subtle">
                            {state.analysis_id}
                          </span>
                        </div>
                        <p className="text-caption mt-1 text-foreground-muted">
                          {MONITOR_DESCRIPTIONS[state.analysis_id] ?? null}
                        </p>
                        {/* Config metadata, demoted. The rung is deliberately absent: the mode is
                            stated once by the pill in the header, and "shadow" is an internal
                            name. */}
                        <p className="text-micro mt-1 font-mono text-foreground-subtle">
                          {state.cadence} · {state.timezone}
                        </p>
                        {/* THE DECLARED NUMBERS, from /analyses. THE CURRENT declaration, not
                            the one that produced any particular alert: synapse.actions freezes
                            the thresholds in force at detection onto each action, which is why
                            the alert detail page shows its own frozen copy and this does not
                            claim to be it. Absent entirely when the registry read failed,
                            rather than rendered as an empty row implying no thresholds. */}
                        {(thresholdsFor.get(state.analysis_id) ?? []).length > 0 ? (
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {(thresholdsFor.get(state.analysis_id) ?? []).map((t) => (
                              <MonoChip key={t.name}>
                                {t.name} {t.days}d
                              </MonoChip>
                            ))}
                          </div>
                        ) : null}
                        {/* WHY A MONITOR RAISED NOTHING, when the run says. Kept on the monitor's
                            own card rather than given a row of its own: it is a property of that
                            run, and Phase A deleted a standalone row here precisely because it
                            described engineering backlog instead of the data. */}
                        <p className="text-micro mt-2 text-foreground-subtle">
                          {monitorNote(state)}
                        </p>
                      </div>
                      {/* THE MOCKUP'S `.mstats` RAIL, WITHOUT ITS "Configure" BUTTON. Nothing in
                          this console configures a monitor: the BFF has no such endpoint and the
                          provisioning grant has no UPDATE on synapse.provision. A button that
                          opens nothing is the dead control this page's whole rule is against. */}
                      <div className="flex shrink-0 flex-col items-end gap-1.5 text-right">
                        <Tag tone="good">Enabled</Tag>
                        <Tag tone="mute">
                          {raised > 0
                            ? `${plural(raised, "alert")} raised last run`
                            : "No alerts last run"}
                        </Tag>
                      </div>
                    </div>
                  </ItemCard>
              );
              })}
            </div>
          )}

          {/* DISABLED MONITORS, WITH NO CONTROL, AND THE ABSENCE IS THE FEATURE.
              Rendered at all because the alternative is invisibility, and an invisible
              disabled pair looks available: the Enable control below would offer it and
              the database would refuse the insert on the primary key, leaving the BFF to
              answer "a row already existed" without being able to say which state it is
              in. This section is how the page says it instead.

              RE-ENABLING IS NOT MISSING, IT IS REFUSED. synapse.provision holds ONE
              window per (tenant, analysis), so clearing disabled_at loses the fact that
              there was a gap and the attribution denominator for that period silently
              becomes wrong. The fix is an append-only enablement history, and the first
              disable is its trigger. The BFF answers 409 with the same explanation, and
              the grant has no UPDATE, so this is the third layer rather than the only
              one. */}
          {detail.disabled_analyses.length > 0 && (
            <div className="mt-6">
              <SectionHead>Switched off</SectionHead>
              <div className="space-y-3">
                {detail.disabled_analyses.map((row) => (
                  <ItemCard key={row.analysis_id}>
                    <div className="flex flex-wrap items-start gap-4">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-subheading text-foreground-muted">
                            {ANALYSIS_NAMES[row.analysis_id] ?? row.analysis_id}
                          </span>
                          <span className="text-micro font-mono text-foreground-subtle">
                            {row.analysis_id}
                          </span>
                        </div>
                        <p className="text-caption mt-1 text-foreground-muted">
                          {MONITOR_DESCRIPTIONS[row.analysis_id] ?? null}
                        </p>
                        <p className="text-micro mt-2 text-foreground-subtle">
                          Ran from {row.enabled_at.slice(0, 10)} to {row.disabled_at.slice(0, 10)}
                        </p>
                      </div>
                      {/* SOLID BORDER, NOT THE DASHED `muted` VARIANT, and the difference carries
                          the meaning the mockup gives it: dashed means AVAILABLE, a monitor that
                          was never provisioned here. This one WAS provisioned and was switched
                          off, which is a different state and the reason this section exists at
                          all. Dashing it would make the two read as one. */}
                      <div className="shrink-0 text-right">
                        <Tag tone="mute">Disabled</Tag>
                      </div>
                    </div>
                  </ItemCard>
                ))}
              </div>
              <div className="mt-3">
                <Footnote>
                  Switching a monitor back on is deliberately not available here. This client has
                  one recorded window per monitor, so re-enabling would overwrite the dates above
                  and the measure of how long each monitor was watching would quietly stop being
                  right. Ask an engineer if a monitor needs to run again.
                </Footnote>
              </div>
            </div>
          )}

          {/* AVAILABLE MONITORS, WITH THE ENABLE CONTROL. The first write surface on this
              page (5e), and every input it does not offer is a safety property: cadence
              and rung are constants in the BFF, the client comes from the route, and the
              monitor comes from this list. The only choice is the reporting timezone, and
              it is chosen once. */}
          {available.length > 0 && (
            <div className="mt-6">
              <SectionHead>Available</SectionHead>
              {/* THE DASHED VARIANT. Both mockups draw a not-yet-provisioned monitor as a
                  dashed card on the raised surface, which is the one place the card treatment
                  carries state rather than decoration: solid is running, dashed is not. */}
              <div className="space-y-3">
                {available.map((row) => (
                  <ItemCard key={row.analysis_id} muted>
                    <div className="flex flex-wrap items-start gap-4">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-subheading text-foreground-muted">
                            {ANALYSIS_NAMES[row.analysis_id] ?? row.name}
                          </span>
                          <span className="text-micro font-mono text-foreground-subtle">
                            {row.analysis_id}
                          </span>
                        </div>
                        <p className="text-caption mt-1 text-foreground-muted">
                          {MONITOR_DESCRIPTIONS[row.analysis_id] ?? null}
                        </p>
                        {row.thresholds.length > 0 ? (
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {row.thresholds.map((t) => (
                              <MonoChip key={t.name}>
                                {t.name} {t.days}d
                              </MonoChip>
                            ))}
                          </div>
                        ) : null}
                      </div>
                      <div className="flex shrink-0 flex-col items-end gap-1.5 text-right">
                        <Tag tone="mute">Available</Tag>
                        {
                          // NO LIST, NO CONTROL. The only input an enable takes is the
                          // timezone, so a component with nothing to offer could render a
                          // button that opens an empty select and an Enable that can never
                          // arm. Rendering the reason instead is the same call the Monitors
                          // tab makes everywhere else.
                          zones.length === 0 ? (
                            <Tag tone="mute">Timezone list unavailable</Tag>
                          ) : (
                            <EnableMonitor
                              tenantId={tenantId}
                              analysisId={row.analysis_id}
                              analysisName={ANALYSIS_NAMES[row.analysis_id] ?? row.name}
                              zones={zones}
                              zoneSource={zoneSource}
                            />
                          )
                        }
                      </div>
                    </div>
                  </ItemCard>
                ))}
              </div>
            </div>
          )}

          <div className="mt-4">
            <Footnote>
              Enabling a monitor starts it watching this client at the next daily sweep, in silent
              mode: it records what it finds here and sends the client nothing. Thresholds shown
              are the current declaration; each alert carries its own frozen copy of the numbers in
              force when it was raised.
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
            <ItemCard>
              <p className="text-body text-foreground-muted">
                No runs recorded for this client yet.
              </p>
            </ItemCard>
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
          {/* THE FACTS GO IN A CARD (B2), the same object as every other list surface here.
              PANEL RATHER THAN A HAND-ROLLED div (B3): this was the only card in Synapse not
              produced by a named component, which made the card recipe two sources of truth.
              The inner padding stays here because Panel deliberately has none, so that its rows
              can carry their own. */}
          <Panel>
            <div className="px-4">
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
            </div>
          </Panel>

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
