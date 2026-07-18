// Phase 5n.4: DIS backend not shipped. Replace with real hook +
// render when DIS APIs ship.

import { FleetPageShell } from "@/components/dis/shared/FleetPageShell";
import { FeaturePending } from "@/components/shared/FeaturePending";

export default function FreshnessPage() {
  return (
    <FleetPageShell
      title="Freshness"
      subtitle="Data-freshness SLO compliance across the fleet."
    >
      <FeaturePending surface="Freshness" eta="DIS APIs ~15 days" />
    </FleetPageShell>
  );
}
