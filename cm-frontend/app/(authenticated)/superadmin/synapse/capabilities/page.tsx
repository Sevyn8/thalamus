import { ChevronRight } from "lucide-react";

import { PageHeader } from "@/components/shared/PageHeader";
import {
  Column,
  Footnote,
  Row,
  SectionHead,
  SubNav,
  SynapseDown,
  Tag,
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
  declined_reason: string | null;
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
          {working.map((c) => (
            <Row
              key={c.capability_id}
              title={c.name}
              meta={
                <>
                  <span className="font-mono">{c.capability_id}</span>
                  {" · "}
                  {c.used_by.length === 0
                    ? "no monitor reads it yet"
                    : `read by ${c.used_by.map((a) => ANALYSIS_NAMES[a] ?? a).join(", ")}`}
                </>
              }
              right={<Tag tone="good">working</Tag>}
            />
          ))}
        </section>

        {/* WHAT SYNAPSE CANNOT DO WAS DOMINATING THE PAGE — honest today, while two
            of four capabilities are unresolved, and noise once most of them work.
            So the section now ANNOUNCES ITS SIZE and disappears entirely at zero,
            which is the half of the disclosure that degrades gracefully.

            NATIVE <details>, NOT AN ACCORDION COMPONENT. There is no disclosure
            primitive in this codebase — nothing in components/ui (17 components),
            nothing in components/shared, nothing in PATTERNS.md. The two
            expand/collapse implementations that DO exist (OrgTreeRow,
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
            {declined.map((c) => (
              <div key={c.capability_id} className="border-b border-border py-3 last:border-b-0">
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
                {/* THE REASON, VERBATIM. "declined" without it flattens "nobody has
                    written this" into "this cannot be written" — the first is a work
                    item, the second is a fact about the data that no amount of code
                    changes. */}
                <p className="text-caption mt-2 text-measure leading-relaxed text-foreground-muted">
                  {c.declined_reason}
                </p>
              </div>
            ))}
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
