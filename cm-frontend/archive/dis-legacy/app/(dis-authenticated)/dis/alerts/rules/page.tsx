// Phase 5n.4: DIS backend not shipped. Replace with real hook +
// render when DIS APIs ship.

import { FleetPageShell } from "@/components/dis/shared/FleetPageShell";
import { FeaturePending } from "@/components/shared/FeaturePending";

export default function AlertRulesPage() {
  return (
    <FleetPageShell
      title="Alert rules"
      subtitle="Configured alert rules across the fleet."
    >
      <FeaturePending surface="Alert rules" eta="DIS APIs ~15 days" />
    </FleetPageShell>
  );
}
