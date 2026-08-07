import { PageHeader } from "@/components/shared/PageHeader";
import { Column, SectionHead } from "@/components/synapse/primitives";

// Atlas — PRESENT, DISABLED, HONEST (D3 / N4).
//
// THERE IS NO API BEHIND THIS PAGE AND THERE MUST NOT BE ONE. A stub endpoint
// returning an empty list is indistinguishable from an endpoint that is broken,
// and this project has removed several artifacts of exactly that shape. The page
// exists so the navigation shape is settled and so nobody wonders whether Atlas
// was forgotten — nothing more.
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
        subtitle="The vocabulary plane. Named in the architecture, not yet started."
      />

      <Column>
        {/* THE PAGE IS BOUNDED; THE PLACEHOLDER STAYS CENTRED INSIDE IT. PATTERNS.md
            specifies the FeaturePending shape as "a minimal centered text + ETA", so
            left-aligning this to match the other five screens would break a
            documented convention to satisfy an undocumented one. Bounding the column
            gives the table below the same proximity as everywhere else without
            touching the empty state's own alignment. */}
        <div className="rounded-md border border-dashed border-border p-8 text-center">
          <p className="text-heading">Atlas is not built</p>
          <p className="text-body mx-auto mt-2 text-measure text-foreground-muted">
            Canonical field meanings, synonyms, and the mapping between a tenant&apos;s language and
            ours. This page has no data behind it because Atlas has no data yet.
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
