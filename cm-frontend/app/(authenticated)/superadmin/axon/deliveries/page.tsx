import { PageHeader } from "@/components/shared/PageHeader";
import {
  Column,
  Footnote,
  ItemCard,
  MonoChip,
  Panel,
  PanelHeader,
  PanelNote,
  PanelRow,
  StatCard,
  StatCards,
  SubNav,
  SynapseDown,
  Tag,
  type Tone,
  plural,
} from "@/components/synapse/primitives";
import {
  SynapseUnavailable,
  fetchDeliveries,
  type DeliveriesResponse,
  type DeliveryRow,
} from "@/lib/axon/server-client";

// NEVER PRERENDER THIS PAGE. It reads the BFF URL and the caller's session at
// request time; prerendering executes it during `next build`, where neither
// exists, and bakes the resulting error notice into static HTML that the
// container then serves for ever. That shipped once, see lib/synapse/server-client.ts.
//
// scripts/assert-dynamic-routes.mjs fails the build if this route comes out
// static, so the directive cannot be silently dropped.
export const dynamic = "force-dynamic";

// ============================================================================
// AXON'S DELIVERY LEDGER. What the platform sent, to whom, and what came back.
// ============================================================================
// BUILT BEFORE THE QUEUE ON PURPOSE. Sending is synchronous today; once it
// becomes async with a dead-letter lane, debugging a queue through psql is
// worse than debugging it with a screen. This is the screen.
//
// ============================================================================
// ACCEPTED IS NOT DELIVERED, AND NOTHING ON THIS PAGE SAYS OTHERWISE
// ============================================================================
// A row records what a provider answered at the moment of sending. SendGrid's
// 202 means it took the message; it does not mean anybody received it. Whether
// mail arrived is knowable only from an inbound delivery receipt, and that plane
// does not exist. So no copy here says sent, delivered or received: the true
// weaker statement degrades gracefully, the plausible specific one becomes a lie
// the first time a message bounces.
//
// ============================================================================
// WHAT IS RENDERED AS AN ID, AND WHY THAT IS NOT LAZINESS
// ============================================================================
// tenant_id renders as an id, not a tenant name. A name needs a join onto
// Customer Master's tenant table, which needs a cross-module SELECT grant on
// axon_reader, and it would be bought to render rows that CANNOT EXIST YET:
// axon.tenant_deliveries is empty and nothing in the platform can write it. The
// join and its grant get argued together when there is something to join.
//
// ============================================================================
// THE ONE COUNT WORTH ACTING ON IS BROKEN OUT
// ============================================================================
// Every suppression reason except one describes a decision the platform made on
// purpose. `channel_not_onboarded` describes a CLIENT receiving nothing while the
// platform believes it is working, and nobody being told. It gets its own card,
// and the card goes amber when it is not zero, because a number folded in beside
// three others is a number nobody reads.
//
// IT READS ZERO TODAY AND CAN READ NOTHING ELSE. There is no tenant channel to be
// un-onboarded. The first non-zero value it ever shows will also be the first
// evidence the query behind it is right.

const SUBTITLE =
  "Every message the platform handed to a provider, newest first, with what came back. " +
  "A provider accepting a message is not the same as somebody receiving it.";

// ---------------------------------------------------------------------------
// GROUPING BY DAY
// ---------------------------------------------------------------------------
// CONTIGUOUS GROUPING, not a Map, exactly as RunHistory does it. The BFF returns
// created_at DESC, so rows for one day arrive adjacent and a change in the key
// starts a group. Re-sorting here would be a second opinion about ordering.
//
// THE DAY IS A UTC DAY AND THE HEADER SAYS SO. There is no per-row timezone to
// group by: a delivery is a platform-wide event, not a tenant's slot, and the
// tenant ledger that would carry a zone holds nothing. Grouping by the viewer's
// local day would put one delivery under different headings for two operators.

type DayGroup = {
  day: string;
  rows: DeliveryRow[];
  accepted: number;
  failed: number;
  suppressed: number;
  // True when this group sits at the end of a truncated response, so its totals
  // are a floor rather than a count. Only the LAST group can be short: the
  // response is ordered by time, so the cap cuts the oldest day in the middle
  // and every group above it is whole.
  partial: boolean;
};

function utcDay(iso: string): string {
  // Slicing the ISO string rather than constructing a Date and formatting it.
  // The BFF returns an ISO-8601 UTC instant, so the first ten characters ARE the
  // UTC date; going through Intl would reintroduce a timezone this page has
  // already decided not to have.
  return iso.slice(0, 10);
}

function groupByDay(rows: DeliveryRow[], truncated: boolean): DayGroup[] {
  const groups: DayGroup[] = [];
  for (const row of rows) {
    let group = groups[groups.length - 1];
    const day = utcDay(row.created_at);
    if (!group || group.day !== day) {
      group = { day, rows: [], accepted: 0, failed: 0, suppressed: 0, partial: false };
      groups.push(group);
    }
    group.rows.push(row);
    if (row.state === "accepted") group.accepted += 1;
    else if (row.state === "failed") group.failed += 1;
    else if (row.state === "suppressed") group.suppressed += 1;
  }
  const last = groups[groups.length - 1];
  if (truncated && last) last.partial = true;
  return groups;
}

// The header line for a day. Only the states actually present are named: "0
// failed" on every healthy day is noise, and a reader learns nothing from a list
// of zeroes.
function daySummary(group: DayGroup): string {
  const parts = [plural(group.rows.length, "delivery", "deliveries")];
  if (group.failed > 0) parts.push(`${group.failed} failed`);
  if (group.suppressed > 0) parts.push(`${group.suppressed} suppressed`);
  return parts.join(" · ");
}

// ---------------------------------------------------------------------------
// THE STATE TAG
// ---------------------------------------------------------------------------
// THE LABEL IS NOT THE STORED VALUE, and the difference is the point. "accepted"
// alone reads to an operator as "it went"; "provider accepted" names who did the
// accepting and stops there. A failure is red because somebody has to look; a
// suppression is neutral because in every reason but one it is the system
// working.
//
// NO DEFAULT THAT INVENTS A LABEL. An unrecognised state renders as itself, so a
// state added to the ledger without being added here appears verbatim rather than
// being silently absorbed into a friendly word that is wrong.
function stateTag(row: DeliveryRow): { label: string; tone: Tone } {
  if (row.state === "accepted") return { label: "provider accepted", tone: "good" };
  if (row.state === "failed") return { label: "send failed", tone: "stop" };
  if (row.state === "suppressed") return { label: "not sent", tone: "mute" };
  return { label: row.state, tone: "mute" };
}

// The time of day, UTC, to the second. Two deliveries a second apart are two
// events an operator may be trying to tell apart.
function utcTime(iso: string): string {
  return iso.slice(11, 19);
}

export default async function DeliveriesPage() {
  let data: DeliveriesResponse;
  try {
    data = await fetchDeliveries();
  } catch (error) {
    if (error instanceof SynapseUnavailable) {
      return (
        <div>
          <PageHeader title="Deliveries" subtitle={SUBTITLE} />
          <Column>
            <SubNav current="deliveries" />
            <SynapseDown message={error.message} />
          </Column>
        </div>
      );
    }
    throw error;
  }

  const { deliveries, truncated, counts } = data;
  const groups = groupByDay(deliveries, truncated);

  return (
    <div>
      <PageHeader title="Deliveries" subtitle={SUBTITLE} />

      <Column>
        <SubNav current="deliveries" />

        {/* FOUR CARDS, AND THEY COUNT THE WHOLE LEDGER RATHER THAN THE PAGE
            BELOW. The list is capped and these are not, so on a truncated page
            they deliberately do not add up to the rows shown. That is the honest
            direction to be wrong in: a total derived from a capped page would be
            a floor presented as a total. */}
        <StatCards columns={4}>
          <StatCard label="Deliveries" value={counts.total} detail="every message, all time" />
          <StatCard
            label="Accepted by a provider"
            value={counts.accepted}
            detail="handed over, not confirmed received"
          />
          <StatCard
            label="Failed"
            value={counts.failed}
            detail="the provider refused or was unreachable"
            warn={counts.failed > 0}
          />
          <StatCard
            label="Blocked, channel not set up"
            value={counts.suppressed_not_onboarded}
            detail="a client is receiving nothing"
            warn={counts.suppressed_not_onboarded > 0}
          />
        </StatCards>

        <section>
          {groups.length === 0 ? (
            <ItemCard>
              <p className="text-body text-foreground-muted">
                Nothing has been sent yet. The platform sends when something happens that a
                person needs to know about, so an empty ledger on a quiet estate is the expected
                reading rather than a fault.
              </p>
            </ItemCard>
          ) : (
            <div className="space-y-4">
              {groups.map((group) => (
                <Panel key={group.day}>
                  <PanelHeader>
                    <span className="text-body-strong font-mono tabular-nums">{group.day}</span>
                    <span className="text-caption text-foreground-muted tabular-nums">
                      {daySummary(group)}
                    </span>
                    <span className="text-micro ml-auto font-mono tabular-nums text-foreground-subtle">
                      UTC
                    </span>
                  </PanelHeader>

                  {group.rows.map((row) => {
                    const tag = stateTag(row);
                    return (
                      <PanelRow key={row.delivery_id}>
                        <div className="w-44 shrink-0">
                          <p className="text-body-strong font-mono tabular-nums">
                            {utcTime(row.created_at)}
                          </p>
                          <p className="text-caption text-foreground-muted">
                            {/* WHICH LEDGER THE ROW CAME FROM. Two rows with the
                                same shape obey different isolation rules, and
                                nothing else on the line distinguishes them. */}
                            {row.scope === "PLATFORM" ? "Sevyn8 internal" : "Tenant"}
                          </p>
                        </div>

                        <div className="shrink-0">
                          <Tag tone={tag.tone} dot={false}>
                            {tag.label}
                          </Tag>
                        </div>

                        <div className="min-w-0 flex-1">
                          <p className="text-body-strong break-all">{row.recipient}</p>
                          <p className="text-caption text-foreground-muted break-all">
                            {/* THE EVENT, AS ITS OWN VOCABULARY. notification_class
                                is the producer's name for what happened; rendering
                                a friendly translation would need a lookup table
                                that goes stale the first time a producer is added
                                without touching this file. */}
                            <span className="font-mono">{row.notification_class}</span> ·{" "}
                            {row.channel} via {row.provider}
                          </p>
                          {row.failure_detail ? (
                            <p className="text-caption mt-1 text-warning">{row.failure_detail}</p>
                          ) : null}
                          <div className="mt-1 flex flex-wrap items-center gap-1.5">
                            {row.suppression_reason ? (
                              <MonoChip>{row.suppression_reason}</MonoChip>
                            ) : null}
                            {/* THE SUBJECT: what the message was about, keyed the
                                way the producer keys it. Shown as a mono value
                                because it is a machine identifier and not a
                                sentence. */}
                            <MonoChip>{row.subject_id}</MonoChip>
                            {/* RENDERED ONLY WHEN THE RESPONSE CARRIES IT. A
                                platform delivery has no tenant, so an absent
                                tenant_id is a fact rather than a gap, and printing
                                a dash for it would invite the reading that one was
                                expected. */}
                            {row.tenant_id ? <MonoChip>{row.tenant_id}</MonoChip> : null}
                          </div>
                        </div>
                      </PanelRow>
                    );
                  })}

                  {group.partial ? (
                    <PanelNote>
                      This day is cut off by the row limit, so its counts above are a floor
                      rather than a total. Older deliveries are in the ledger and not on this
                      page.
                    </PanelNote>
                  ) : null}
                </Panel>
              ))}
            </div>
          )}

          <div className="mt-4">
            <Footnote>
              A provider accepting a message means it took responsibility for it, not that
              anybody read it. Nothing here can tell you a message arrived, because nothing in
              the platform is told: that needs a delivery receipt coming back from the provider,
              which is a separate piece of work.{" "}
              <span className="font-mono">not sent</span> rows were never handed over at all, and
              the reason beside each one says why.
            </Footnote>
          </div>
        </section>
      </Column>
    </div>
  );
}
