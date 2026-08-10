import { PageHeader } from "@/components/shared/PageHeader";
import {
  CONTROL_CLASS,
  Column,
  FilterBar,
  FilterChip,
  FilterGroup,
  Footnote,
  ItemCard,
  Panel,
  PanelRow,
  SectionHead,
  AlertStateTag,
  UnknownStateTag,
  asAlertState,
  SilentModePill,
  SubNav,
  SynapseDown,
  isOpen,
  plural,
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

// The fleet alerts inbox.
//
// WHAT DID NOT EXIST BEFORE THIS PAGE. Alerts were reachable only one tenant at a
// time: an operator had to already suspect a client to find its alerts. Nothing
// answered "what needs a person right now, anywhere". The two endpoints behind
// this page (GET /alerts, GET /alerts/state-counts) are new for the same reason.
//
// THE STATE IS THE SERVER'S, AND NOW IT IS THE SERVER'S EVERYWHERE. This comment
// used to say every OTHER Synapse screen derived the state in the browser, and
// that collapsing the derivations was Phase B. B2a did it: the TypeScript
// deriver is deleted, every alert-bearing endpoint serves lifecycle_state from
// one SQL CASE, and this page is no longer the exception.
//
// It mattered most here first because this list is FILTERED on the state in SQL,
// so recomputing it would create a second opinion that can disagree with the
// query that selected the row: a row returned as snoozed could render as open,
// one day either side of the boundary. That argument turned out to apply to the
// counts on the fleet and tenant pages too, which is what B2a fixed.

type FleetAlert = {
  event_id: string;
  tenant_id: string;
  tenant_name: string;
  as_of: string;
  recorded_at: string;
  declaration_id: string;
  quantity_at_stake: string | null;
  days_since_last_sale: number | null;
  days_of_cover: string | null;
  store_id: string | null;
  sku_id: string | null;
  store_name: string | null;
  product_name: string | null;
  lifecycle_state: string;
  lifecycle_reason: string | null;
  lifecycle_snoozed_until: string | null;
};

type FleetTenant = { tenant_id: string; name: string };
type AnalysisCatalogRow = { analysis_id: string; name: string };

// Says the mode once, in the same words the fleet page uses. The per-row "not
// sent to client (silent mode)" the mockup repeated on every line is NOT here:
// the pill in the header, this sentence and the closing footnote already say it,
// and a fourth copy on each of a hundred rows is the thing Footnote exists to
// avoid.
const SUBTITLE =
  "Every alert across every client, newest first. Each row opens the full finding. " +
  "In silent mode, alerts are recorded here but never sent to clients.";

const LIMIT = 100;

// The four the BFF's ALERT_STATES declares, in the order an operator works them:
// what is live, what was deferred, what was seen, what was closed.
const STATES = ["open", "snoozed", "acknowledged", "dismissed"] as const;

const STATE_LABEL: Record<string, string> = {
  open: "Open",
  snoozed: "Snoozed",
  acknowledged: "Acknowledged",
  dismissed: "Dismissed",
};

// A NUMERIC column arrives as a string so no precision is lost in JSON. Number()
// here is for rounding to one place in the sentence below, not for storage.
function cover(value: string | null): number | null {
  if (value === null) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

// The evidence phrase under each alert: what the monitor actually measured.
//
// THE TILDE STAYS. days_of_cover is a Decimal and rendering 5.04 as "5 days"
// asserts a precision the figure does not have. The approximation marker is what
// keeps a rounded number honest, and it costs one character.
//
// NO SIBLING-STORE CLAUSE, which the mockup had ("never sold at this store; sells
// at Ambienace"). days_since_last_sale is measured per store, and whether the SKU
// moves at another store is not computed anywhere and is not on this row. The
// sentence stops where the data stops.
function evidence(alert: FleetAlert): string | null {
  const days = cover(alert.days_of_cover);
  if (days !== null) return `~${days.toFixed(1)} days of cover at current rate`;
  if (alert.days_since_last_sale !== null) {
    return `${plural(alert.days_since_last_sale, "day")} since the last sale at this store`;
  }
  // NULL IS A STRONGER FACT THAN A NUMBER on this monitor, not missing data: the
  // store has never sold the product. The detail page says the same thing at
  // length, and rendering it as "0 days" would invert the meaning. Said only for
  // dead_stock, because a null on any other monitor asserts nothing.
  if (alert.declaration_id === "dead_stock") return "never sold at this store";
  return null;
}

// NO "by <user>", which the mockup also had ("snoozed until 16 Aug by
// amit@sevyn8.com"). action_events records an Auth0 subject and nothing in this
// deployment maps a subject to a name: the Action stamps no name claim, so both
// consoles already derive display names from email addresses. Naming a person
// here would mean inventing one. The date is real and stays.
function lifecycleNote(alert: FleetAlert): string | null {
  if (alert.lifecycle_state === "snoozed" && alert.lifecycle_snoozed_until) {
    return `reappears ${alert.lifecycle_snoozed_until}`;
  }
  return null;
}

// StateChip WAS HERE AND IS NOW FilterChip IN primitives.tsx (B2). It was an outline pill of its
// own recipe; the mockup draws a SEGMENTED GROUP whose active chip is solid primary, and that is
// now a shared component because the same control belongs on any Synapse list that grows filters.
//
// THE CHIPS ARE THE COUNTS, WHICH IS WHY THE STAT STRIP IS GONE. This page rendered the same four
// lifecycle numbers twice: a StatStrip of four figures at the top, and these four chips directly
// beneath it. The mockup has no strip at all, and it is not withholding anything by leaving it
// out: each chip is both the number and the control that filters to it. What the strip alone
// carried was the amber on a non-zero open count, and the segmented group carries emphasis
// differently, by which chip is filled.

export default async function AlertsInboxPage({
  searchParams,
}: {
  searchParams: Promise<{ state?: string; analysis_id?: string; tenant_id?: string }>;
}) {
  const filters = await searchParams;

  const query = new URLSearchParams({ limit: String(LIMIT) });
  if (filters.state) query.set("state", filters.state);
  if (filters.analysis_id) query.set("analysis_id", filters.analysis_id);
  if (filters.tenant_id) query.set("tenant_id", filters.tenant_id);

  let alerts: FleetAlert[];
  let counts: Record<string, number>;
  try {
    // The chips and the list are two calls ON PURPOSE. The list is capped at
    // LIMIT; the counts are not. Deriving chips from the returned page would
    // understate every number the moment the cap bites, and would also change
    // as the filters narrow, which is the opposite of what a filter chip is for.
    [{ alerts }, { states: counts }] = await Promise.all([
      synapseGet<{ alerts: FleetAlert[] }>(`/alerts?${query.toString()}`),
      synapseGet<{ states: Record<string, number> }>("/alerts/state-counts"),
    ]);
  } catch (error) {
    if (!(error instanceof SynapseUnavailable)) throw error;
    return (
      <div>
        <PageHeader title="Alerts" subtitle={SUBTITLE} rightSlot={<SilentModePill />} />
        <Column>
          <SubNav current="alerts" />
          <SynapseDown message={error.message} />
        </Column>
      </div>
    );
  }

  // THE OPTION LISTS DEGRADE TO NOTHING rather than taking the page down with
  // them. A filter is an accessory to the list; the list is what an operator came
  // for. Empty options render as a disabled control below rather than as an
  // empty dropdown pretending there is nothing to choose.
  let tenants: FleetTenant[] = [];
  let analyses: AnalysisCatalogRow[] = [];
  try {
    [{ tenants }, { analyses }] = await Promise.all([
      synapseGet<{ tenants: FleetTenant[] }>("/fleet"),
      synapseGet<{ analyses: AnalysisCatalogRow[] }>("/analyses"),
    ]);
  } catch (error) {
    if (!(error instanceof SynapseUnavailable)) throw error;
  }

  const filtered = Boolean(filters.state || filters.analysis_id || filters.tenant_id);
  const chipHref = (state: string) => {
    const next = new URLSearchParams();
    if (filters.analysis_id) next.set("analysis_id", filters.analysis_id);
    if (filters.tenant_id) next.set("tenant_id", filters.tenant_id);
    // Clicking the active chip clears it. See StateChip.
    if (filters.state !== state) next.set("state", state);
    const qs = next.toString();
    return qs ? `?${qs}` : "/superadmin/synapse/alerts";
  };

  return (
    <div>
      <PageHeader title="Alerts" subtitle={SUBTITLE} rightSlot={<SilentModePill />} />

      <Column>
        <SubNav current="alerts" />

        {/* A PLAIN GET FORM, no JavaScript and no client component. Submitting
            navigates to this same route with the selections in the query string,
            which is exactly what the server component reads. The state chips are
            carried as hidden fields so choosing a monitor does not silently drop
            the state the operator had already picked. */}
        <form method="get" action="/superadmin/synapse/alerts" className="flex flex-col gap-3">
          <FilterBar>
            <FilterGroup>
              {STATES.map((state) => (
                <FilterChip
                  key={state}
                  active={filters.state === state}
                  href={chipHref(state)}
                >
                  {STATE_LABEL[state] ?? state}{" "}
                  <span className="tabular-nums">{counts[state] ?? 0}</span>
                </FilterChip>
              ))}
            </FilterGroup>
            {/* THE CHIPS ARE FLEET-WIDE AND SAY SO WHILE A FILTER IS ON.
                /alerts/state-counts takes no parameters: the counts are of the
                whole fleet by construction, deliberately, because deriving them
                from the returned page would understate every number the moment
                the limit bites. That is right and it READS as a bug when the
                list beside them is filtered to nothing, so the qualifier appears
                exactly when the two can disagree.

                A FILTERED COUNT IS NOT AVAILABLE. There is no per-filter count
                endpoint, and counting the returned rows would produce a floor
                capped at the list limit, which is the class of claim B2a removed
                from the tenant page. The screen states the number it has and
                names its scope rather than implying a narrower one. */}
            {filtered ? (
              <span className="text-micro text-foreground-subtle">counts are fleet-wide</span>
            ) : null}
          </FilterBar>

          {filters.state ? <input type="hidden" name="state" value={filters.state} /> : null}

          <FilterBar>
            <label className="text-caption text-foreground-muted" htmlFor="analysis_id">
              Monitor
            </label>
            <select
              id="analysis_id"
              name="analysis_id"
              defaultValue={filters.analysis_id ?? ""}
              disabled={analyses.length === 0}
              className={CONTROL_CLASS}
            >
              <option value="">All</option>
              {analyses.map((a) => (
                <option key={a.analysis_id} value={a.analysis_id}>
                  {ANALYSIS_NAMES[a.analysis_id] ?? a.name}
                </option>
              ))}
            </select>

            <label className="text-caption ml-2 text-foreground-muted" htmlFor="tenant_id">
              Client
            </label>
            <select
              id="tenant_id"
              name="tenant_id"
              defaultValue={filters.tenant_id ?? ""}
              disabled={tenants.length === 0}
              className={CONTROL_CLASS}
            >
              <option value="">All</option>
              {tenants.map((t) => (
                <option key={t.tenant_id} value={t.tenant_id}>
                  {t.name}
                </option>
              ))}
            </select>

            <button
              type="submit"
              className={`${CONTROL_CLASS} border-border-strong bg-surface-raised`}
            >
              Apply
            </button>
            {filtered ? (
              <a
                href="/superadmin/synapse/alerts"
                className="text-caption text-primary underline-offset-2 hover:underline"
              >
                Clear filters
              </a>
            ) : null}
          </FilterBar>
        </form>

        {/* NO STORE FILTER, and the omission is deliberate rather than forgotten.
            The endpoint takes store_id, but nothing in the BFF returns a
            fleet-wide list of stores to populate a chooser from, and store names
            are not unique across clients. A dropdown built from the returned page
            would silently omit every store whose alerts fell past the cap, which
            is a control that lies about its own options. It arrives with a store
            list, not before one. */}

        <section>
          <SectionHead>
            {filters.state ? `${STATE_LABEL[filters.state] ?? filters.state} alerts` : "All alerts"}
          </SectionHead>

          {alerts.length === 0 ? (
            /* THE EMPTY STATE CARRIES THE FLEET-WIDE NUMBER, which is what makes
               "Open 6" beside an empty list stop reading as a contradiction. Both
               statements were already true and the screen only made one of them:
               the chip said how many exist anywhere, the list said none match
               here, and nothing on the page connected the two. Now the sentence
               that explains the emptiness is the one that names the other number.

               Uses the counts already fetched for the chips, so this costs no
               request and cannot disagree with them. */
            <ItemCard>
              <p className="text-body text-foreground-muted">
                {filtered
                  ? `No alerts match these filters. Across all monitors and clients, ${plural(
                      counts.open ?? 0,
                      "alert",
                    )} ${(counts.open ?? 0) === 1 ? "is" : "are"} open.`
                  : "No alerts have been raised yet, by any monitor, for any client."}
              </p>
            </ItemCard>
          ) : (
            /* ONE CARD, ROWS INSIDE IT (B2). The mockup's inbox is a single surface whose
               children are ruled rows, which is the third of the four treatments and needs no
               new component: Panel with PanelRow children is exactly it.

               THE ROW'S CONTENT IS UNCHANGED, AND THE MOCKUP IS NOT FOLLOWED ON ITS LAYOUT. It
               leads each row with a pill naming the MONITOR and demotes the lifecycle state to
               grey text on the right, then contradicts itself: its snoozed row replaces the
               monitor pill with a "Snoozed" one, so that row no longer says which monitor raised
               it. The state is the thing an operator filters and acts on, so it keeps the tag,
               and the monitor keeps its place in the meta line. Visual slice, and the information
               architecture stays where B2a and B2b put it. */
            <Panel>
              {alerts.map((alert) => {
                // Narrowed once, here, at the wire boundary. See asAlertState.
                const state = asAlertState(alert.lifecycle_state);
                // ATTENTION ONLY WHILE IT IS OPEN, matching the tenant page. A
                // snoozed, acknowledged or dismissed alert is still a recorded
                // finding and stays on the list, but it stops shouting.
                const attention = state !== null && isOpen(state);
                const note = lifecycleNote(alert);
                return (
                  <PanelRow key={alert.event_id}>
                    <div className="min-w-0 flex-1">
                      <p
                        className={
                          attention ? "text-body-strong text-warning" : "text-body-strong"
                        }
                      >
                        <a
                          className="text-primary underline-offset-2 hover:underline"
                          href={`/superadmin/synapse/tenants/${alert.tenant_id}/alerts/${alert.event_id}`}
                        >
                          {alert.product_name ?? alert.sku_id ?? "Unknown product"}
                        </a>
                      </p>
                      <p className="text-caption mt-0.5 text-foreground-muted">
                        {alert.tenant_name}
                        {alert.store_name ? ` · ${alert.store_name}` : ""} ·{" "}
                        {ANALYSIS_NAMES[alert.declaration_id] ?? alert.declaration_id}
                        {evidence(alert) ? ` · ${evidence(alert)}` : ""}
                      </p>
                      <p className="text-micro mt-1 font-mono text-foreground-subtle">
                        {alert.sku_id ?? "no SKU on this alert"} · raised {alert.as_of}
                      </p>
                    </div>
                    <div className="shrink-0 text-right">
                      {state === null ? (
                        <UnknownStateTag state={alert.lifecycle_state} />
                      ) : (
                        <AlertStateTag
                          state={state}
                          reason={alert.lifecycle_reason}
                          snoozedUntil={alert.lifecycle_snoozed_until}
                        />
                      )}
                      {note ? (
                        <p className="text-micro mt-1 text-foreground-subtle">{note}</p>
                      ) : null}
                    </div>
                  </PanelRow>
                );
              })}
            </Panel>
          )}

          <div className="mt-3 space-y-2">
            {alerts.length >= LIMIT ? (
              <Footnote>
                Showing the {LIMIT} most recent alerts. Narrow by state, monitor or client to
                reach older ones.
              </Footnote>
            ) : null}
            <Footnote>
              A repeat of the same finding on a later day is a new alert, not an update to this
              one, and a decision taken on a product at a store carries forward to those repeats.
              Nothing here has been sent to a client.
            </Footnote>
          </div>
        </section>
      </Column>
    </div>
  );
}
