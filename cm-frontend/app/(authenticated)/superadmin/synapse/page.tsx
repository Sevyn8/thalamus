import { PageHeader } from "@/components/shared/PageHeader";
import { SectionHead, SynapseDown, Tag, Tile, daysSince } from "@/components/synapse/primitives";
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

export default async function SynapseFleetPage() {
  let tenants: FleetRow[];
  try {
    ({ tenants } = await synapseGet<{ tenants: FleetRow[] }>("/fleet"));
  } catch (error) {
    if (error instanceof SynapseUnavailable) {
      // SAYS WHICH THING IS DOWN. "Something went wrong" would send an operator
      // to the wrong system; this names the BFF so the next step is obvious.
      return (
        <div className="space-y-6">
          <PageHeader title="Synapse" subtitle="Watching, and telling nobody yet." />
          <SynapseDown message={error.message} />
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
  const actions = tenants.reduce((sum, t) => sum + t.actions_recorded, 0);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Synapse"
        subtitle="Watching, and telling nobody yet. Everything is at the shadow rung."
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Tile n={live.length} label="tenants live" />
        <Tile n={live.reduce((s, t) => s + t.analyses_running, 0)} label="analyses running" />
        <Tile n={actions} label="actions ever" />
        <Tile n={stale.length} label="needs a person" warn={stale.length > 0} />
      </div>

      {stale.length > 0 && (
        <section>
          <SectionHead>Needs you</SectionHead>
          {stale.map((t) => {
            const age = daysSince(t.latest_sale);
            return (
              <div key={t.tenant_id} className="border-b border-border py-3 last:border-b-0">
                <p className="text-body-strong">
                  {age === null
                    ? `${t.name} has never sent a sale`
                    : `${t.name}'s sales data is ${age} days old`}
                </p>
                <p className="mt-0.5 text-body text-foreground-muted">
                  {age === null
                    ? "Every rate-based analysis will refuse until something ingests."
                    : `Last sale ${t.latest_sale}. Every rate-based analysis is refusing, correctly, and will until something ingests.`}
                </p>
              </div>
            );
          })}
        </section>
      )}

      <section>
        <SectionHead>Tenants</SectionHead>
        {tenants.length === 0 ? (
          // A REAL STATE, rendered as itself. D6: no placeholder content to make
          // the screen look finished.
          <p className="text-body text-foreground-muted">
            No tenants are mirrored yet, so there is nothing for Synapse to watch.
          </p>
        ) : (
          tenants.map((t) => (
            <div key={t.tenant_id} className="flex items-center gap-3 border-b border-border py-3 last:border-b-0">
              <div>
                <a
                  className="text-body-strong underline-offset-2 hover:underline"
                  href={`/superadmin/synapse/tenants/${t.tenant_id}`}
                >
                  {t.name}
                </a>
                <p className="text-body text-foreground-muted">
                  {t.stores} stores · {t.products} products
                  {t.last_run_slot ? ` · last ran ${t.last_run_slot}` : ""}
                </p>
              </div>
              <span className="ml-auto">
                <Tag tone={t.analyses_running > 0 ? "good" : "mute"}>
                  {t.analyses_running > 0 ? `${t.analyses_running} · watching` : "nothing on"}
                </Tag>
              </span>
            </div>
          ))
        )}
      </section>

      <p className="font-mono text-caption text-foreground-muted">
        &quot;watching&quot; is what the shadow rung is called here · the client is not told and
        nothing reaches them
      </p>
    </div>
  );
}
