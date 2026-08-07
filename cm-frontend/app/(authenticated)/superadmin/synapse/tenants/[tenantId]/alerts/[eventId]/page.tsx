import { notFound } from "next/navigation";

import { PageHeader } from "@/components/shared/PageHeader";
import {
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
} from "@/components/synapse/primitives";
import { ANALYSIS_NAMES } from "@/lib/synapse/names";
import { SynapseUnavailable, synapseGet } from "@/lib/synapse/server-client";

// NEVER PRERENDER THIS PAGE. It reads SYNAPSE_BFF_URL and the caller's session at
// request time; prerendering executes it during `next build`, where neither exists,
// and bakes the resulting error notice into static HTML the container serves for
// ever. scripts/assert-dynamic-routes.mjs fails the build if this comes out static.
export const dynamic = "force-dynamic";

// 5c — one recorded alert, in full. READ-ONLY END TO END: no Snooze, no Dismiss, no
// Mark actioned. Those are 5d's and there is no lifecycle column behind them yet, so
// rendering them disabled would be a promise the data cannot keep.

type Alert = {
  event_id: string;
  as_of: string;
  recorded_at: string;
  declaration_id: string;
  declaration_version: string;
  verb: string;
  arm: string;
  expires_on: string;
  quantity_at_stake: string | null;
  days_since_last_sale: number | null;
  days_of_cover: string | null;
  thresholds: Record<string, number>;
  store_id: string | null;
  sku_id: string | null;
  store_name: string | null;
  product_name: string | null;
  current_stock_qty: string | null;
};

type HistoryRow = {
  event_id: string;
  as_of: string;
  quantity_at_stake: string | null;
  days_since_last_sale: number | null;
  days_of_cover: string | null;
};

type AlertDetail = { alert: Alert; history: HistoryRow[] };

// A number the backend sends as a NUMERIC string. Trailing zeros are an artefact of
// the column's scale (14,3), not a measurement, so "40.000" reads as 40.
function units(value: string | null): string | null {
  if (value === null) return null;
  const n = Number(value);
  return Number.isFinite(n) ? String(n) : value;
}

// WHY THIS WAS FLAGGED, in plain English.
//
// THE THRESHOLD COMES FROM THE ROW, NEVER FROM LIVE CONFIG. `alert.thresholds` is
// provenance frozen onto the action when it was recorded, so an alert raised under
// an older threshold explains itself with the number that actually fired. Reading
// today's declaration instead would silently rewrite history the next time somebody
// retunes a monitor — the row would keep its values and change its reason.
function whyFlagged(alert: Alert): string {
  const monitor = ANALYSIS_NAMES[alert.declaration_id] ?? alert.declaration_id;

  if (alert.declaration_id === "dead_stock") {
    const limit = alert.thresholds["stale_after_days"];
    // NULL IS A STRONGER FACT THAN ANY NUMBER, not missing data: the store has never
    // sold this product. Rendering it as "0 days" would invert the meaning.
    if (alert.days_since_last_sale === null) {
      return `This store has never sold this product. The ${monitor} monitor treats never-sold as its strongest signal.`;
    }
    const tail = limit === undefined ? "" : ` The ${monitor} monitor flags anything past ${limit}.`;
    return `No sales at this store for ${alert.days_since_last_sale} days.${tail}`;
  }

  if (alert.declaration_id === "stockout_risk") {
    const limit = alert.thresholds["at_risk_below_days"];
    const cover = units(alert.days_of_cover);
    if (cover === null) {
      return `The ${monitor} monitor raised this without a cover figure on the row.`;
    }
    const tail = limit === undefined ? "" : ` The ${monitor} monitor flags anything under ${limit}.`;
    return `About ${cover} days of stock left at the recent rate of sale.${tail}`;
  }

  // An analysis this page has no sentence for. Says what it knows rather than
  // inventing prose for a monitor it has not been taught.
  return `Raised by the ${monitor} monitor on ${alert.as_of}.`;
}

export default async function AlertDetailPage({
  params,
}: {
  params: Promise<{ tenantId: string; eventId: string }>;
}) {
  const { tenantId, eventId } = await params;

  let detail: AlertDetail;
  try {
    detail = await synapseGet<AlertDetail>(`/tenants/${tenantId}/alerts/${eventId}`);
  } catch (error) {
    if (error instanceof SynapseUnavailable) {
      return (
        <div>
          <PageHeader title="Alert" rightSlot={<SilentModePill />} />
          <Column>
            <SynapseDown message={error.message} />
          </Column>
        </div>
      );
    }
    // 404 covers "no such alert" AND "that alert belongs to another client"; the BFF
    // cannot tell them apart by design, so neither can this page.
    notFound();
  }

  const { alert, history } = detail;
  const product = alert.product_name ?? alert.sku_id ?? "Unknown product";
  const atDetection = units(alert.quantity_at_stake);
  const current = units(alert.current_stock_qty);

  return (
    <div>
      <PageHeader
        title={product}
        subtitle="One alert raised by a monitor. Nothing here was sent to the client."
        rightSlot={<SilentModePill />}
      />

      <Column>
        <Breadcrumb
          tenant="Client"
          tenantHref={`/superadmin/synapse/tenants/${tenantId}`}
          current={product}
        />

        <section>
          <SectionHead>The product</SectionHead>
          <Row
            title={product}
            meta={
              <>
                {alert.store_name ?? "Store no longer in the client directory"}
                <span className="text-micro mt-1 block font-mono text-foreground-subtle">
                  {alert.sku_id ?? "no SKU on this alert"}
                </span>
              </>
            }
            right={<Tag tone="mute">not sent to client (silent mode)</Tag>}
          />
        </section>

        <section>
          <SectionHead>The numbers</SectionHead>
          {/* TWO TIMEFRAMES, LABELLED. "At detection" is frozen on the alert; "current"
              is today's position. A product that has since sold out must read as
              recovered rather than as this page contradicting itself. */}
          <StatStrip>
            <Stat n={atDetection ?? "—"} label="units at detection" />
            <Stat n={current ?? "—"} label="units in stock now" />
            <Stat n={alert.as_of} label="raised (slot)" />
          </StatStrip>
          {atDetection === null && (
            <Footnote>
              The monitor recorded no quantity for this position, which is not the same as
              zero — a stock figure was unavailable when it ran.
            </Footnote>
          )}
        </section>

        <section>
          <SectionHead>Why it was flagged</SectionHead>
          <p className="text-body text-foreground">{whyFlagged(alert)}</p>
          <Footnote>
            Judged against the thresholds recorded with this alert, not against the monitor&apos;s
            current settings — so an older alert keeps explaining itself the way it was raised.
          </Footnote>
        </section>

        <section>
          <SectionHead>History</SectionHead>
          {history.length === 0 ? (
            <p className="text-body text-foreground-muted">
              This is the only time this alert has been recorded.
            </p>
          ) : (
            history.map((row) => (
              <Row
                key={row.event_id}
                title={row.as_of}
                meta={
                  row.days_since_last_sale !== null
                    ? `${row.days_since_last_sale} days since a sale`
                    : units(row.days_of_cover) !== null
                      ? `${units(row.days_of_cover)} days of cover`
                      : "no evidence figures recorded"
                }
                right={
                  units(row.quantity_at_stake) !== null ? (
                    <span className="text-caption font-mono text-foreground-muted">
                      {units(row.quantity_at_stake)} units
                    </span>
                  ) : undefined
                }
              />
            ))
          )}
          {/* THE HONEST CAVEAT, and it is load-bearing. Re-raising the same alert on the
              same day is suppressed by the idempotency index and writes NOTHING, so a
              missing day is silence, not resolution. Without this line a reader would
              read the gap as the problem having gone away. */}
          <Footnote>
            Re-raising the same alert on the same day is suppressed and leaves no record, so a
            day missing here means the monitor did not raise it again — not that the problem was
            resolved.
          </Footnote>
        </section>
      </Column>
    </div>
  );
}
