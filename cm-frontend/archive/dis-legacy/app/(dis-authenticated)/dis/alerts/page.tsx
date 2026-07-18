// Phase 5n.4: DIS backend not shipped. Replace with real hook +
// render when DIS APIs ship.

import { FleetPageShell } from "@/components/dis/shared/FleetPageShell";
import { FeaturePending } from "@/components/shared/FeaturePending";

export default function AlertsPage() {
  return (
    <FleetPageShell
      title="Alerts"
      subtitle="Pipeline alert events across the fleet."
    >
      <FeaturePending surface="Alerts" eta="DIS APIs ~15 days" />
    </FleetPageShell>
  );
}
