import { notFound } from "next/navigation";

import { PageHeader } from "@/components/shared/PageHeader";
import {
  NameWithId,
  SectionHead,
  SynapseDown,
  Tag,
  Tile,
  Unavailable,
  daysSince,
  type Tone,
} from "@/components/synapse/primitives";
import { ANALYSIS_NAMES } from "@/lib/synapse/names";
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

// THE THREE-STATE RENDERING (D5), and the middle case is the honest one.
//
// A run that proposed zero is either "found no risk" or "refused everything as
// stale". synapse.run.detail — the column that would say which — exists and is
// empty, so the data does not distinguish them. Reporting either would be a
// guess; this reports the truth and points at the missing column.
function found(state: AnalysisState): { tone: Tone; label: string } {
  if (state.last_outcome === null) return { tone: "mute", label: "has not run yet" };
  if (state.last_outcome === "failed") return { tone: "stop", label: "last run failed" };
  if (state.last_outcome === "blocked") return { tone: "unknown", label: "blocked" };
  const proposed = state.actions_proposed ?? 0;
  if (proposed > 0) return { tone: "good", label: `${proposed} found` };
  return { tone: "unknown", label: "0 · reason not recorded" };
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
        <div className="space-y-6">
          <PageHeader title="Synapse" subtitle="One tenant" />
          <SynapseDown message={error.message} />
        </div>
      );
    }
    throw error;
  }

  const staleDays = daysSince(detail.latest_sale);

  return (
    <div className="space-y-6">
      <PageHeader
        title={detail.name}
        subtitle="Watching. Nothing here reaches the client — every analysis is at the shadow rung."
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Tile n={detail.products} label="products watched" />
        <Tile n={detail.sales_seen} label="sales seen" />
        <Tile n={detail.actions_recorded} label="actions recorded" />
        <Tile
          n={staleDays === null ? "—" : `${staleDays}d`}
          label={staleDays === null ? "no sale ever seen" : "since the last sale"}
          warn={staleDays === null || staleDays > 3}
        />
      </div>

      <SectionHead>Running</SectionHead>
      {detail.analyses.length === 0 ? (
        // A granted-but-unprovisioned tenant is a real state (D6). Rendered as
        // itself rather than padded to look finished.
        <p className="text-body text-foreground-muted">
          Nothing is provisioned for this tenant, so Synapse is not watching it. Provisioning is
          done by hand until the write path exists.
        </p>
      ) : (
        detail.analyses.map((state) => {
          const verdict = found(state);
          return (
            <div key={state.analysis_id} className="flex items-start gap-3 border-b border-border py-3">
              <NameWithId
                name={ANALYSIS_NAMES[state.analysis_id] ?? state.analysis_id}
                id={state.analysis_id}
              />
              <div className="ml-auto flex flex-col items-end gap-1">
                <Tag tone={verdict.tone}>{verdict.label}</Tag>
                <span className="font-mono text-caption text-foreground-muted">
                  {state.cadence} · {state.timezone} · {state.rung}
                </span>
              </div>
            </div>
          );
        })
      )}

      <SectionHead>What the last run could and could not tell us</SectionHead>
      <table className="w-full text-body">
        <tbody>
          {/* REAL: read straight off canonical by the BFF. */}
          <tr className="border-b">
            <td className="py-3 text-foreground-muted">Most recent sale</td>
            <td className="py-3 text-right text-micro font-mono">
              {detail.latest_sale ?? "none has ever arrived"}
              {staleDays !== null ? ` · ${staleDays} days ago` : ""}
            </td>
            <td className="max-w-prose py-3 pl-4 text-caption text-foreground-muted">
              Every rate-based analysis refuses a series older than its freshness threshold,
              because dividing today&apos;s stock by a rate that stopped weeks ago mixes two
              instants.
            </td>
          </tr>

          {/* REAL: synapse.run's own counts. proposed vs appended differ when the
              idempotency index suppresses a repeat, which is worth seeing. */}
          {detail.analyses.map((state) => (
            <tr key={state.analysis_id} className="border-b">
              <td className="py-3 text-foreground-muted">
                Last run · {ANALYSIS_NAMES[state.analysis_id] ?? state.analysis_id}
              </td>
              <td className="py-3 text-right text-micro font-mono">
                {state.last_slot
                  ? `${state.last_slot} · ${state.last_outcome} · proposed ${state.actions_proposed ?? 0}, appended ${state.actions_appended ?? 0}`
                  : "never"}
              </td>
              <td className="max-w-prose py-3 pl-4 text-caption text-foreground-muted">
                Appended can be lower than proposed: a repeat of the same slot is suppressed by
                the idempotency index rather than duplicated.
              </td>
            </tr>
          ))}

          {/* NOT REAL, AND SAID SO. Naming the column is the point — the gap is
              legible rather than mysterious. */}
          <Unavailable
            what="Why each product was refused"
            because="synapse.run.detail exists and is empty. counts_by_reason() already computes the breakdown in code; threading it into the run row is a Plan-signature change (outstanding item 4). Until then a run that proposed 0 cannot be told apart from one that found nothing."
          />
        </tbody>
      </table>

      <p className="font-mono text-caption text-foreground-muted">
        no product is named on this screen · the tenant-facing view is 8b and is counts-only
      </p>
    </div>
  );
}
