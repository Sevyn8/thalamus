import { PageHeader } from "@/components/shared/PageHeader";

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
    <div className="space-y-6">
      <PageHeader
        title="Atlas"
        subtitle="The vocabulary plane. Named in the architecture, not yet started."
      />

      <div className="rounded-md border border-dashed border-border p-8 text-center">
        <p className="text-heading">Atlas is not built</p>
        <p className="mx-auto mt-2 max-w-prose text-body text-foreground-muted">
          Canonical field meanings, synonyms, and the mapping between a tenant&apos;s
          language and ours. This page has no data behind it because Atlas has no
          data yet.
        </p>
      </div>

      <section>
        <h2 className="text-label mb-3 text-foreground-subtle">
          What it will own
        </h2>
        <table className="w-full text-body">
          <tbody>
            {OWNS_EVENTUALLY.map((row) => (
              <tr key={row.concern} className="border-b border-border last:border-b-0">
                <td className="py-3">{row.concern}</td>
                <td className="py-3 text-right font-mono text-caption text-foreground-muted">
                  today: {row.today}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
