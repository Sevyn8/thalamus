// Phase 5n.4: DIS backend not shipped. Replace with real hook +
// render when DIS APIs ship.

import { FleetPageShell } from "@/components/dis/shared/FleetPageShell";
import { FeaturePending } from "@/components/shared/FeaturePending";

export default function FleetHealthPage() {
  return (
    <FleetPageShell
      title="Fleet health"
      subtitle="Pipeline-wide health across all tenants."
    >
      <FeaturePending surface="Fleet health" eta="DIS APIs ~15 days" />
    </FleetPageShell>
  );
}
