import { ChevronRight } from "lucide-react";

import { PageHeader } from "@/components/shared/PageHeader";
import {
  Column,
  Footnote,
  Panel,
  PanelRow,
  SectionHead,
  SubNav,
  SynapseDown,
  TableCard,
  Tag,
  Td,
  Th,
  Tr,
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

// E1 — what Synapse can read, and what it cannot.
//
// THIS TABLE IS THE REGISTRY AND NOTHING ELSE. The build spec listed seven
// capabilities, taken from an architecture document, on a page whose stated
// premise was that every figure came from staging. The registry holds FOUR.
// basket_set, identity_series and detections are named nowhere in it, so
// rendering them would present a wish as system state — and it would be
// invisible, because seven plausible rows look exactly like seven real ones.
//
// The BFF derives every row from registered_ids() and declined_ids(), so this
// page cannot show a capability that does not exist or omit one that does.

type CapabilityView = {
  capability_id: string;
  name: string;
  resolves: boolean;
  // SERVED AND DELIBERATELY NOT RENDERED, the same call as ThresholdView.stands_in_for.
  // _DECLINED's reason is a verified audit note: it classifies a column as a MAPPING-PRODUCED
  // declared scalar, cites dis_validation.provenance, and records that a RECEIPT subtype was
  // "verified by grep across services, libs, mappings and connectors". Every word earns its
  // place in the registry; none of it belongs on a console.
  declined_reason: string | null;
  // The same fact in one operator-facing sentence. Guaranteed present for a declined capability
  // by test_every_declined_capability_has_an_operator_summary in the BFF.
  declined_summary: string | null;
  used_by: string[];
};

export default async function CapabilitiesPage() {
  let capabilities: CapabilityView[];
  try {
    ({ capabilities } = await synapseGet<{ capabilities: CapabilityView[] }>("/capabilities"));
  } catch (error) {
    if (error instanceof SynapseUnavailable) {
      return (
        <div>
          <PageHeader title="Capabilities" subtitle="What Synapse can read." />
          <Column>
            <SubNav current="capabilities" />
            <SynapseDown message={error.message} />
          </Column>
        </div>
      );
    }
    throw error;
  }

  const working = capabilities.filter((c) => c.resolves);
  const declined = capabilities.filter((c) => !c.resolves);

  return (
    <div>
      <PageHeader
        title="Capabilities"
        subtitle={`${working.length} of ${capabilities.length} resolve. Every row comes from the registry; none is aspirational.`}
      />

      <Column>
        <SubNav current="capabilities" />
        <section>
          <SectionHead>Working</SectionHead>
          {/* THE TABLE IN A CARD (B2), which is the mockup's treatment for this page.
              `Consumed by` is its most useful column and is the reverse index of each
              analysis's requires list, which the BFF already computes as `used_by`.

              THREE OF THE MOCKUP'S FIVE COLUMNS ARE ABSENT AND THE REASON IS THE SAME EACH
              TIME: `Kind` (series / point / aggregate), `Grain` (tenant · store · sku) and
              `Freshness` are properties of the capability DECLARATION, and GET /capabilities
              serves capability_id, name, resolves, declined_reason, declined_summary and
              used_by. Nothing projects a kind, a grain or a freshness policy over the wire.
              Each would be a fourth, fifth and sixth <Th> here the day it is served; until
              then a column of invented values would be worse than a narrower table.

              NO ROW HOVER, because nothing here opens. The roster's rows are clickable and
              carry one; a hover that suggests a click which does not exist is a dead
              affordance. */}
          <TableCard
            head={
              <>
                <Th className="w-[32%]">Capability</Th>
                <Th>Consumed by</Th>
                <Th className="w-[14%]">Status</Th>
              </>
            }
          >
            {working.map((c) => (
              <Tr key={c.capability_id}>
                <Td>
                  <p className="text-body-strong">{c.name}</p>
                  <p className="text-micro mt-0.5 font-mono text-foreground-subtle">
                    {c.capability_id}
                  </p>
                </Td>
                {/* THE PLAIN NAMES, NOT THE MOCKUP'S MONO IDS. It draws this column as
                    `<span class="tag">stockout_risk</span>`, and swapping the operator-facing
                    names for wire ids would be a copy change wearing a visual slice's clothes:
                    D4 is plain language in the UI with the id beside it, never the id alone.
                    The sentence is exactly the one this cell already carried. */}
                <Td className="text-caption text-foreground-muted">
                  {c.used_by.length === 0
                    ? "no monitor reads it yet"
                    : `read by ${c.used_by.map((a) => ANALYSIS_NAMES[a] ?? a).join(", ")}`}
                </Td>
                <Td>
                  <Tag tone="good">working</Tag>
                </Td>
              </Tr>
            ))}
          </TableCard>
        </section>

        {/* WHAT SYNAPSE CANNOT DO WAS DOMINATING THE PAGE — honest today, while two
            of four capabilities are unresolved, and noise once most of them work.
            So the section now ANNOUNCES ITS SIZE and disappears entirely at zero,
            which is the half of the disclosure that degrades gracefully.

            NATIVE <details>, NOT AN ACCORDION COMPONENT. There is no disclosure
            primitive in this codebase — nothing in components/ui, nothing in
            components/shared. The two expand/collapse implementations that DO
            exist (OrgTreeRow,
            PermissionMatrixGroup) are bespoke CLIENT-side state machines, and
            adopting either would turn this server component into a client island
            purely to hide some rows. <details> is the platform doing it with no
            state, no JavaScript and no "use client" — which is the only reason this
            page can stay server-rendered, and staying server-rendered is what keeps
            the BFF unreachable from a browser.

            The caret is lucide's ChevronRight rotated by group-open, matching
            OrgTreeRow's caret; the summary carries SectionHead's own classes so the
            heading does not change appearance by becoming interactive. */}
        {declined.length > 0 && (
          <details className="group">
            <summary className="text-label mt-6 mb-3 flex cursor-pointer list-none items-center gap-1.5 border-b border-border pb-1.5 text-foreground-subtle select-none [&::-webkit-details-marker]:hidden">
              <ChevronRight className="h-3 w-3 transition-transform duration-150 ease-out group-open:rotate-90" />
              {declined.length} of {capabilities.length} not available yet
            </summary>
            {/* ROWS IN ONE CARD (B3). These were hand-rolled ruled rows on the page background,
                directly beneath a Working section that became a TableCard in B2, which left the
                two halves of one page in two different languages. Panel and PanelRow rather than
                a second TableCard because each of these carries a WRAPPED SENTENCE, and a
                sentence that wraps is a row rather than a cell. */}
            <Panel>
              {declined.map((c) => (
                <PanelRow key={c.capability_id}>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start gap-4">
                      <div className="min-w-0 flex-1">
                        <p className="text-body-strong">{c.name}</p>
                        <p className="text-caption font-mono text-foreground-muted">
                          {c.capability_id}
                        </p>
                      </div>
                      <span className="shrink-0">
                        <Tag tone="stop">no data exists</Tag>
                      </span>
                    </div>
                    {/* THE REASON, IN ONE SENTENCE. Saying only "not available"
                        flattens "nobody has written this" into "this cannot be
                        written": the first is a work item, the second is a fact about
                        the data that no amount of code changes, and an operator needs
                        to know which.

                        THIS RENDERED declined_reason VERBATIM UNTIL B2b-2. That value
                        is an audit note citing dis_validation.provenance and a grep
                        across four package trees, written for whoever revisits the
                        decision. It is unchanged and still served; the console now
                        draws the operator-facing summary beside it. */}
                    <p className="text-caption mt-2 text-measure leading-relaxed text-foreground-muted">
                      {c.declined_summary ?? "No reason has been recorded for this capability."}
                    </p>
                  </div>
                </PanelRow>
              ))}
            </Panel>
          </details>
        )}

        <Footnote>
          A capability missing from this page is not necessarily impossible; it may simply have no
          entry yet. An entry under <span className="font-mono">not available</span> carries a
          verified reason, which is a stronger claim and is why the list is short.
        </Footnote>
      </Column>
    </div>
  );
}
