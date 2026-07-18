// Phase 5n.4: DIS backend not shipped. Replace with real hook +
// render when DIS APIs ship.

import { FleetPageShell } from "@/components/dis/shared/FleetPageShell";
import { FeaturePending } from "@/components/shared/FeaturePending";

export default function BackfillsPage() {
  return (
    <FleetPageShell
      title="Backfills"
      subtitle="Historical-data backfill operations across the fleet."
    >
      <FeaturePending surface="Backfills" eta="DIS APIs ~15 days" />
    </FleetPageShell>
  );
}
