import { PageHeader } from "@/components/shared/PageHeader";
import {
  Attention,
  Column,
  ItemCard,
  SectionHead,
  SilentModePill,
  StatCard,
  StatCards,
  SubNav,
  SynapseDown,
  TableCard,
  Tag,
  Td,
  Th,
  Tr,
  daysSince,
  plural,
} from "@/components/synapse/primitives";
import { SynapseUnavailable, synapseGet } from "@/lib/synapse/server-client";

// NEVER PRERENDER THIS PAGE. It reads SYNAPSE_BFF_URL and the caller's session at
// request time; prerendering executes it during `next build`, where neither
// exists, and bakes the resulting error notice into static HTML that the
// container then serves for ever. That shipped once — see lib/synapse/server-client.ts.
//
// scripts/assert-dynamic-routes.mjs fails the build if this route comes out
// static, so the directive cannot be silently dropped.
export const dynamic = "force-dynamic";

// R1 — the fleet. Synapse's index.
//
// A SERVER COMPONENT, which is a deliberate divergence from every other page in
// this app. The others are "use client" and fetch cm-backend from the BROWSER
// with the user's Auth0 token. This one runs on the server and calls the Synapse
// BFF with a Google ID token, so the BFF needs no public invoker binding, no
// Synapse data reaches the browser, and there is no CORS surface.
//
// OPENS ON WHAT NEEDS A PERSON, not a list of everything.

type FleetRow = {
  tenant_id: string;
  name: string;
  analyses_running: number;
  actions_recorded: number;
  open_alerts: number;
  last_run_slot: string | null;
  latest_sale: string | null;
  stores: number;
  products: number;
};

// The strictest freshness threshold any analysis declares. A tenant whose latest
// sale is older than this has every rate-based analysis refusing — correctly, and
// invisibly, because those runs SUCCEED. This panel is currently the only thing
// in the project that can see it: no execution-status alert ever will.
const STALE_AFTER_DAYS = 3;

// The one place the mode is explained. It replaces both "Watching, and telling nobody yet" and
// the footer paragraph that defined "watching" — a definition nobody reads at the bottom of a
// page is worse than a sentence at the top that makes the pill mean something.
const SUBTITLE =
  "Monitors watch each client's sales data and raise alerts when something needs attention. " +
  "In silent mode, alerts are recorded here but never sent to clients.";

// Three states, in priority order, and none of them is "watching".
//
// A tenant with alerts OR stale data is amber: both are things a person should look at, and a
// tenant that is both says so on one pill rather than needing two. Everything else is a neutral
// outline, because "nothing to report" and "nothing configured" are not achievements.
// PRECEDENCE FOLLOWS THE ONBOARDING ORDER: connect a data source, then enable monitors. A client
// with neither used to read "No monitors enabled", which names the SECOND thing missing and sends
// an operator to configure monitors that would have nothing to watch.
//
//   1. no data ever      -> "Waiting for data"        the first step, and it blocks the rest
//   2. no monitors       -> "No monitors enabled"     data is in; nothing is watching it
//   3. alerts exist      -> "N alerts raised"         with a stale-data suffix if both are true
//   4. stale             -> "Stale data"
//   5. otherwise         -> "No alerts"
function fleetStatus(t: FleetRow): string {
  if (t.latest_sale === null) return "Waiting for data";
  if (t.analyses_running === 0) return "No monitors enabled";
  const stale = staleness(t);
  if (t.actions_recorded > 0) {
    return stale
      ? `${plural(t.actions_recorded, "alert")} raised · stale data`
      : `${plural(t.actions_recorded, "alert")} raised`;
  }
  return stale ? "Stale data" : "No alerts";
}

// TONE MOVES WITH THE CHAIN or the two desync. Rows 1, 2 and 5 are neutral — "waiting for data"
// and "nothing configured" are onboarding states, not problems, and amber on them would make a
// brand-new client look broken. Rows 3 and 4 are the ones a person should look at.
function fleetTone(t: FleetRow): "unknown" | "mute" {
  if (t.latest_sale === null) return "mute";
  if (t.analyses_running === 0) return "mute";
  return t.actions_recorded > 0 || staleness(t) ? "unknown" : "mute";
}

function staleness(t: FleetRow): boolean {
  const age = daysSince(t.latest_sale);
  return age === null || age > STALE_AFTER_DAYS;
}

// THE DATA FRESHNESS COLUMN (B2). Derived from `latest_sale`, which this page already reads for
// the banner and for fleetStatus above, so the column adds a rendering rather than a claim.
//
// ITS PRECEDENCE IS THE MOCKUPS' ONE RULE FOR THIS ROSTER: data health outranks monitor status,
// so a client with no data says so here before the Status column says anything. The two columns
// coincide at "Waiting for data" and that is the mockup's own design rather than an accident: the
// state where they agree is exactly the state where nothing else is worth saying.
function freshness(t: FleetRow): { label: string; tone: "good" | "unknown" | "mute" } {
  const age = daysSince(t.latest_sale);
  if (age === null) return { label: "Waiting for data", tone: "mute" };
  return { label: `${plural(age, "day")} old`, tone: age > STALE_AFTER_DAYS ? "unknown" : "good" };
}

export default async function SynapseFleetPage() {
  let tenants: FleetRow[];
  try {
    ({ tenants } = await synapseGet<{ tenants: FleetRow[] }>("/fleet"));
  } catch (error) {
    if (error instanceof SynapseUnavailable) {
      // SAYS WHICH THING IS DOWN. "Something went wrong" would send an operator
      // to the wrong system; this names the BFF so the next step is obvious.
      return (
        <div>
          <PageHeader title="Synapse" subtitle={SUBTITLE} rightSlot={<SilentModePill />} />
          <Column>
            <SubNav current="overview" />
            <SynapseDown message={error.message} />
          </Column>
        </div>
      );
    }
    throw error;
  }

  const live = tenants.filter((t) => t.analyses_running > 0);
  const stale = live.filter((t) => {
    const age = daysSince(t.latest_sale);
    return age === null || age > STALE_AFTER_DAYS;
  });
  const monitorsRunning = live.reduce((s, t) => s + t.analyses_running, 0);
  const alertsRaised = tenants.reduce((sum, t) => sum + t.actions_recorded, 0);
  const openAlerts = tenants.reduce((sum, t) => sum + t.open_alerts, 0);

  return (
    <div>
      <PageHeader title="Synapse" subtitle={SUBTITLE} rightSlot={<SilentModePill />} />

      <Column>
        <SubNav current="overview" />
        {/* THE THING NEEDING A PERSON IS A BANNER, NOT A ROW THAT LOOKS LIKE THE
            OTHERS. It also comes before the stats: a count of problems is less
            useful than the problem, and "needs a person: 1" as a tile was the
            same information styled as trivia. */}
        {stale.map((t) => {
          const age = daysSince(t.latest_sale);
          return (
            <Attention
              key={t.tenant_id}
              title={
                age === null
                  ? `${t.name} has never sent a sale`
                  : `${t.name}'s sales data is ${plural(age, "day")} stale`
              }
              detail={
                age === null
                  ? "No sale has ever been ingested. Rate-based monitors will find nothing until fresh data arrives."
                  : `Last sale ingested ${t.latest_sale}. Rate-based monitors will find nothing until fresh data arrives.`
              }
            />
          );
        })}

        {/* STAT CARDS HERE AND NOWHERE ELSE (B2). The overview is the only mockup with stats of
            any kind: the alerts inbox puts its counts inside the filter chips, and the tenant
            mockup uses a meta line and a freshness pill. Giving every Synapse page cards because
            one page has them would be the uniformity error in the other direction, so the tenant
            Overview tab and the alert detail page keep the inline strip. */}
        <StatCards>
          <StatCard value={live.length} label={live.length === 1 ? "client live" : "clients live"} />
          <StatCard
            value={monitorsRunning}
            label={monitorsRunning === 1 ? "monitor running" : "monitors running"}
          />
          {/* "OPEN" IS SAYABLE NOW. This comment used to read: "'Alerts raised', NOT 'open
              alerts'… there is no lifecycle column on synapse.actions and no way to close one,
              so 'open' would name a state the system cannot represent." Migration 0006 gives it
              one — an operator can snooze, dismiss or acknowledge — so the state exists and the
              headline is the number somebody can act on.

              BOTH ARE SHOWN. The all-time count is the attribution denominator D1 protects, and
              quietly redefining it under the same label would change what an old screenshot
              meant. Open leads because it is the actionable one. */}
          {/* THE NUMBER IS THE WAY IN. The fleet inbox is the screen that answers
              "what needs a person, anywhere", and this figure is the reason
              somebody would want it. Linking the count rather than adding a
              separate button keeps the strip a strip. */}
          <StatCard
            value={
              <a
                className="underline-offset-4 hover:underline"
                href="/superadmin/synapse/alerts"
              >
                {openAlerts}
              </a>
            }
            label={openAlerts === 1 ? "open alert" : "open alerts"}
          />
          <StatCard
            value={alertsRaised}
            label={alertsRaised === 1 ? "alert raised" : "alerts raised"}
          />
        </StatCards>

        <section>
          <SectionHead>Tenants</SectionHead>
          {tenants.length === 0 ? (
            // A REAL STATE, rendered as itself. D6: no placeholder content to make
            // the screen look finished.
            <ItemCard>
              <p className="text-body text-foreground-muted">
                No tenants are mirrored yet, so there is nothing for Synapse to watch.
              </p>
            </ItemCard>
          ) : (
            /* THE ROSTER IS A TABLE NOW (B2), which is the mockups' treatment for this screen
               and for the tenants list. Every fact was already on the page: stores, products and
               monitors were a single meta line under the name, the status pill is unchanged, and
               the last run sat at the end of that line. A column lets a reader compare one fact
               DOWN the fleet, which is what a roster is opened to do and what a stack of rows
               cannot support however it is styled.

               NO "LAST SWEEP REFUSALS" COLUMN, which both mockups carry as their last one.
               GET /fleet serves nine fields and none is a refusal breakdown: the counts live on
               synapse.run per (tenant, analysis) and reach the console only through /runs and
               /tenants/{id}. Adding the column would mean either a BFF change, which this slice
               does not make, or summing something this response does not contain. The day /fleet
               carries it, the column is one <Td> here.

               NO ADOPTION BAR AND NO "of 5 types", which the tenants-list mockup draws beside the
               monitor count. The registry declares TWO analyses, so the denominator would be
               invented and the bar would be a picture of a number nobody stores. */
            <TableCard
              head={
                <>
                  <Th className="w-[26%]">Tenant</Th>
                  <Th>Stores</Th>
                  <Th>Products</Th>
                  <Th>Data freshness</Th>
                  <Th>Monitors</Th>
                  <Th>Status</Th>
                  <Th>Last run</Th>
                </>
              }
            >
              {tenants.map((t) => {
                const fresh = freshness(t);
                return (
                  <Tr key={t.tenant_id} interactive>
                    <Td>
                      <a
                        className="text-body-strong underline-offset-2 hover:underline"
                        href={`/superadmin/synapse/tenants/${t.tenant_id}`}
                      >
                        {t.name}
                      </a>
                    </Td>
                    <Td className="text-body tabular-nums">{t.stores}</Td>
                    <Td className="text-body tabular-nums">{t.products}</Td>
                    <Td>
                      <Tag tone={fresh.tone}>{fresh.label}</Tag>
                    </Td>
                    <Td className="text-body tabular-nums">{t.analyses_running}</Td>
                    {/* THE PILL ENCODES HEALTH, NOT IMPLEMENTATION STATE. It used to read
                        "2 analyses · watching" in GREEN, which said what the system was doing
                        and coloured a client's dead stock as good news. An alert is not good
                        news, so the count leads and the tone is amber; green stays available in
                        Tag for things that are genuinely good. */}
                    <Td>
                      <Tag tone={fleetTone(t)}>{fleetStatus(t)}</Tag>
                    </Td>
                    <Td className="text-caption font-mono tabular-nums text-foreground-muted">
                      {t.last_run_slot ?? "never"}
                    </Td>
                  </Tr>
                );
              })}
            </TableCard>
          )}
        </section>
      </Column>
    </div>
  );
}
