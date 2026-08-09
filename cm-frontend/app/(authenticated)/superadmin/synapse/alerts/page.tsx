import { PageHeader } from "@/components/shared/PageHeader";
import {
  Column,
  Footnote,
  Row,
  SectionHead,
  ServerStateTag,
  SilentModePill,
  Stat,
  StatStrip,
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
// THE STATE IS THE SERVER'S, NOT THIS FILE'S. Every other Synapse screen derives
// the lifecycle state in the browser from the raw columns (alertState). Here the
// list is FILTERED on the state in SQL, so recomputing it would create a second
// opinion that can disagree with the query that selected the row: a row returned
// as snoozed could render as open, one day either side of the boundary. The BFF's
// derivation evaluates expiry in UTC, matching what the TypeScript side compares
// against. Collapsing the two derivations into one is Phase B.

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

// A filter chip that is a LINK, not a button, so it works with no JavaScript and
// so its target is visible in the status bar before it is clicked. The active one
// links back to the unfiltered list, which is what a reader expects a pressed
// chip to do and means no chip is ever inert.
function StateChip({
  state,
  count,
  active,
  href,
}: {
  state: string;
  count: number;
  active: boolean;
  href: string;
}) {
  return (
    <a
      href={href}
      className={`text-caption rounded-full border px-3 py-1 transition-colors duration-150 ease-out ${
        active
          ? "border-border-strong bg-surface-raised text-foreground"
          : "border-border text-foreground-muted hover:border-border-strong hover:text-foreground"
      }`}
    >
      {STATE_LABEL[state] ?? state} <span className="font-mono">{count}</span>
    </a>
  );
}

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
        <StatStrip>
          {STATES.map((state) => (
            <Stat
              key={state}
              n={counts[state] ?? 0}
              label={STATE_LABEL[state] ?? state}
              // ONLY OPEN CARRIES COLOUR. Three amber figures would emphasise
              // nothing; open is the one somebody has to do something about.
              warn={state === "open" && (counts[state] ?? 0) > 0}
            />
          ))}
        </StatStrip>

        {/* A PLAIN GET FORM, no JavaScript and no client component. Submitting
            navigates to this same route with the selections in the query string,
            which is exactly what the server component reads. The state chips are
            carried as hidden fields so choosing a monitor does not silently drop
            the state the operator had already picked. */}
        <form method="get" action="/superadmin/synapse/alerts" className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            {STATES.map((state) => (
              <StateChip
                key={state}
                state={state}
                count={counts[state] ?? 0}
                active={filters.state === state}
                href={chipHref(state)}
              />
            ))}
          </div>

          {filters.state ? <input type="hidden" name="state" value={filters.state} /> : null}

          <div className="flex flex-wrap items-center gap-2">
            <label className="text-caption text-foreground-muted" htmlFor="analysis_id">
              Monitor
            </label>
            <select
              id="analysis_id"
              name="analysis_id"
              defaultValue={filters.analysis_id ?? ""}
              disabled={analyses.length === 0}
              className="text-caption rounded border border-border bg-surface px-2 py-1.5 text-foreground disabled:text-foreground-subtle"
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
              className="text-caption rounded border border-border bg-surface px-2 py-1.5 text-foreground disabled:text-foreground-subtle"
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
              className="text-caption rounded border border-border-strong bg-surface-raised px-3 py-1.5 text-foreground transition-colors duration-150 ease-out hover:border-border-strong"
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
          </div>
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
            <p className="text-body text-foreground-muted">
              {filtered
                ? "No alerts match these filters."
                : "No alerts have been raised yet, by any monitor, for any client."}
            </p>
          ) : (
            alerts.map((alert) => (
              <Row
                key={alert.event_id}
                // ATTENTION ONLY WHILE IT IS OPEN, matching the tenant page. A
                // dismissed alert is still a recorded finding and stays on the
                // list, but it stops shouting.
                attention={isOpen(alert.lifecycle_state)}
                title={
                  <a
                    className="text-primary underline-offset-2 hover:underline"
                    href={`/superadmin/synapse/tenants/${alert.tenant_id}/alerts/${alert.event_id}`}
                  >
                    {alert.product_name ?? alert.sku_id ?? "Unknown product"}
                  </a>
                }
                meta={
                  <>
                    {alert.tenant_name}
                    {alert.store_name ? ` · ${alert.store_name}` : ""} ·{" "}
                    {ANALYSIS_NAMES[alert.declaration_id] ?? alert.declaration_id}
                    {evidence(alert) ? ` · ${evidence(alert)}` : ""}
                    <span className="text-micro mt-1 block font-mono text-foreground-subtle">
                      {alert.sku_id ?? "no SKU on this alert"} · raised {alert.as_of}
                    </span>
                  </>
                }
                right={
                  <ServerStateTag
                    state={alert.lifecycle_state}
                    reason={alert.lifecycle_reason}
                    snoozedUntil={alert.lifecycle_snoozed_until}
                  />
                }
                note={lifecycleNote(alert) ?? undefined}
              />
            ))
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
