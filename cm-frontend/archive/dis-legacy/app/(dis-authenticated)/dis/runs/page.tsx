// Phase 5n.4: DIS backend not shipped. Replace with real hook +
// render when DIS APIs ship.

import { FleetPageShell } from "@/components/dis/shared/FleetPageShell";
import { FeaturePending } from "@/components/shared/FeaturePending";

export default function RunsPage() {
  return (
    <FleetPageShell
      title="Runs"
      subtitle="Pipeline runs across the fleet."
    >
      <FeaturePending surface="Runs" eta="DIS APIs ~15 days" />
    </FleetPageShell>
  );
}
