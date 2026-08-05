import { PageHeader } from "@/components/shared/PageHeader";
import { NameWithId, SectionHead, SynapseDown, Tag } from "@/components/synapse/primitives";
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
        <div className="space-y-6">
          <PageHeader title="Capabilities" subtitle="What Synapse can read." />
          <SynapseDown message={error.message} />
        </div>
      );
    }
    throw error;
  }

  const working = capabilities.filter((c) => c.resolves);
  const declined = capabilities.filter((c) => !c.resolves);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Capabilities"
        subtitle={`${working.length} of ${capabilities.length} resolve. Every row comes from the registry; none is aspirational.`}
      />

      <SectionHead>Working</SectionHead>
      <table className="w-full text-body">
        <tbody>
          {working.map((c) => (
            <tr key={c.capability_id} className="border-b border-border last:border-b-0">
              <td className="py-3">
                <NameWithId name={c.name} id={c.capability_id} />
              </td>
              <td className="py-3 text-body text-foreground-muted">
                {c.used_by.length === 0
                  ? "no analysis reads it yet"
                  : `read by ${c.used_by.map((a) => ANALYSIS_NAMES[a] ?? a).join(", ")}`}
              </td>
              <td className="py-3 text-right">
                <Tag tone="good">working</Tag>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {declined.length > 0 && (
        <>
          <SectionHead>Cannot be built</SectionHead>
          {declined.map((c) => (
            <div key={c.capability_id} className="border-b border-border py-3 last:border-b-0">
              <div className="flex items-start gap-3">
                <NameWithId name={c.name} id={c.capability_id} />
                <span className="ml-auto">
                  <Tag tone="stop">no data exists</Tag>
                </span>
              </div>
              {/* THE REASON, VERBATIM. "declined" without it flattens "nobody has
                  written this" into "this cannot be written" — the first is a work
                  item, the second is a fact about the data that no amount of code
                  changes. */}
              <p className="mt-2 text-caption max-w-prose leading-relaxed text-foreground-muted">
                {c.declined_reason}
              </p>
            </div>
          ))}
        </>
      )}

      <p className="max-w-prose text-caption text-foreground-muted">
        A capability missing from this page is not necessarily impossible — it may simply have no
        entry yet. An entry under <span className="font-mono">cannot be built</span> carries a
        verified reason, which is a stronger claim and is why the list is short.
      </p>
    </div>
  );
}
