import { notFound } from "next/navigation";

import { PageHeader } from "@/components/shared/PageHeader";
import {
  Breadcrumb,
  Column,
  Fact,
  Facts,
  Footnote,
  Row,
  SectionHead,
  Stat,
  StatStrip,
  SynapseDown,
  Tag,
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

  const staleDays = daysSince(detail.latest_sale);

  return (
    <div>
      <PageHeader
        title={detail.name}
        subtitle="Watching. Nothing here reaches the client — every analysis is at the shadow rung."
      />

      <Column>
        <Breadcrumb tenant={detail.name} />

        {/* ONLY THE STALENESS IS COLOURED. Four emphasised figures emphasise
            nothing; this is the one an operator can act on. */}
        <StatStrip>
          <Stat n={detail.products} label="products watched" />
          <Stat n={detail.sales_seen} label="sales seen" />
          <Stat n={detail.actions_recorded} label="actions recorded" />
          <Stat
            n={staleDays === null ? "—" : `${staleDays}d`}
            label={staleDays === null ? "no sale ever seen" : "since the last sale"}
            warn={staleDays === null || staleDays > 3}
          />
        </StatStrip>

        <section>
          <SectionHead>Running</SectionHead>
          {detail.analyses.length === 0 ? (
            // A granted-but-unprovisioned tenant is a real state (D6). Rendered as
            // itself rather than padded to look finished.
            <p className="text-body text-foreground-muted">
              Nothing is provisioned for this tenant, so Synapse is not watching it. Provisioning
              is done by hand until the write path exists.
            </p>
          ) : (
            detail.analyses.map((state) => {
              const verdict = found(state);
              const hasNeverRun = state.last_outcome === null;
              return (
                <Row
                  key={state.analysis_id}
                  attention={hasNeverRun}
                  title={ANALYSIS_NAMES[state.analysis_id] ?? state.analysis_id}
                  // METADATA WITH ITS SUBJECT, and the internal id belongs here
                  // too: it is what appears in logs and in synapse.run, so a
                  // screen without it makes a log line unsearchable from the UI
                  // that produced it. That is D4, and it survives the layout
                  // change even though the component that used to carry it does not.
                  meta={
                    <span className="font-mono">
                      {state.analysis_id} · {state.cadence} · {state.timezone} · {state.rung}
                    </span>
                  }
                  right={<Tag tone={verdict.tone}>{verdict.label}</Tag>}
                  // NO CLOCK TIME HERE, deliberately. The mockup reads "First run
                  // tomorrow 03:00", but the schedule (30 21 * * * UTC) lives in
                  // terraform and is NOT in the BFF's response — cadence and
                  // timezone are. Rendering an hour would be inventing a figure on
                  // a screen whose whole premise is that every number is real.
                  note={hasNeverRun ? `first run at the next ${state.cadence} slot` : undefined}
                />
              );
            })
          )}
        </section>

        <section>
          <SectionHead>What the last run could and could not tell us</SectionHead>
          <Facts>
            {/* REAL: read straight off canonical by the BFF. */}
            <Fact
              label="Most recent sale"
              value={detail.latest_sale ?? "none has ever arrived"}
              note={staleDays !== null ? `${staleDays} days ago` : undefined}
            />

            {/* REAL: synapse.run's own counts. The explanation that used to be
                repeated on every one of these rows is now the footnote below. */}
            {detail.analyses.map((state) => (
              <Fact
                key={state.analysis_id}
                label={`${ANALYSIS_NAMES[state.analysis_id] ?? state.analysis_id} · last run`}
                value={state.last_slot ?? "never"}
                note={
                  state.last_slot
                    ? `${state.last_outcome} · ${state.actions_proposed ?? 0} proposed, ${state.actions_appended ?? 0} appended`
                    : undefined
                }
              />
            ))}

            {/* NOT REAL, AND SAID SO. Naming the column is the point — the gap is
                legible rather than mysterious. */}
            <Unavailable
              what="Why each product was refused"
              because="synapse.run.detail exists and is empty. counts_by_reason() already computes the breakdown in code; threading it into the run row is a Plan-signature change (outstanding item 4). Until then a run that proposed 0 cannot be told apart from one that found nothing."
            />
          </Facts>

          {/* ONE FOOTNOTE, COVERING BOTH FACTS. It was two rows of prose saying
              one of these things twice. */}
          <div className="mt-3">
            <Footnote>
              Every rate-based analysis refuses a series older than its freshness threshold, because
              dividing today&apos;s stock by a rate that stopped weeks ago mixes two instants. Where
              appended is lower than proposed, a repeat of the same slot was suppressed by the
              idempotency index rather than duplicated.
            </Footnote>
          </div>
        </section>

        <Footnote>
          No product is named on this screen. The tenant-facing view is 8b and is counts-only.
        </Footnote>
      </Column>
    </div>
  );
}
