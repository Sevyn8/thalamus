import { PageHeader } from "@/components/shared/PageHeader";
import { Column, SectionHead } from "@/components/synapse/primitives";

// Atlas - URL-ONLY, AND DEFERRED INDEFINITELY.
//
// THIS PAGE IS NOT IN THE NAVIGATION. Its sidebar entry was removed in Axon slice
// 3 and the header here is the record of why. The page is reachable by typing
// /superadmin/atlas and by nothing else.
//
// WHY THE ORIGINAL ARGUMENT NO LONGER HOLDS. D3/N4 kept Atlas present and
// disabled so the navigation shape was settled and nobody wondered whether it had
// been forgotten. That was correct WHILE ATLAS WAS NEXT IN LINE. It is now
// deferred indefinitely: zero code, no module behind it, and nothing scheduled.
// A permanent entry stops reading as "coming" and starts reading as "in progress"
// about something nobody is building, which misinforms every operator who sees
// it. The reason to show it and the reason to remove it are the same reason.
//
// THE PAGE IS KEPT RATHER THAN DELETED, and the two are different changes.
// Removing the route as well would discard the only written record of what Atlas
// is meant to own and where each of those concerns lives today, which is worth
// more than the URL costs.
//
// THERE IS NO API BEHIND THIS PAGE AND THERE MUST NOT BE ONE. A stub endpoint
// returning an empty list is indistinguishable from an endpoint that is broken,
// and this project has removed several artifacts of exactly that shape.
//
// Each row names where that concern lives TODAY, which is what makes Atlas a
// consolidation of things that exist rather than an invention.

const OWNS_EVENTUALLY: ReadonlyArray<{ concern: string; today: string }> = [
  { concern: "Canonical field definitions", today: "DDL comments" },
  { concern: "Tenant vocabulary mapping", today: "mapping templates in DIS" },
  { concern: "Signal definitions and units", today: "Synapse's signal contract" },
];

export default function AtlasPage() {
  return (
    <div>
      <PageHeader
        title="Atlas"
        subtitle="The vocabulary plane. Named in the architecture, deferred indefinitely, and not in the navigation."
      />

      <Column>
        {/* THE PAGE IS BOUNDED; THE PLACEHOLDER STAYS CENTRED INSIDE IT. PATTERNS.md
            specifies the FeaturePending shape as "a minimal centered text + ETA", so
            left-aligning this to match the other five screens would break a
            documented convention to satisfy an undocumented one. Bounding the column
            gives the table below the same proximity as everywhere else without
            touching the empty state's own alignment. */}
        <div className="rounded-md border border-dashed border-border p-8 text-center">
          <p className="text-heading">Atlas is not being built</p>
          <p className="text-body mx-auto mt-2 text-measure text-foreground-muted">
            Canonical field meanings, synonyms, and the mapping between a tenant&apos;s language and
            ours. This page has no data behind it because Atlas has no data yet, and no work is
            scheduled. Its sidebar entry was removed so it does not read as something in
            progress.
          </p>
        </div>

        <section>
          <SectionHead>What it will own</SectionHead>
          <table className="w-full">
            <tbody>
              {OWNS_EVENTUALLY.map((row) => (
                <tr key={row.concern} className="border-b border-border last:border-b-0">
                  <td className="text-body py-3 pr-4">{row.concern}</td>
                  <td className="text-caption py-3 text-right font-mono text-foreground-muted">
                    today: {row.today}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </Column>
    </div>
  );
}
