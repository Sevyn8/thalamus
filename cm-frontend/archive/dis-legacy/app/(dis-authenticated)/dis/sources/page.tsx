// Phase 5n.4: DIS backend not shipped. Replace with real hook +
// render when DIS APIs ship.

import { FleetPageShell } from "@/components/dis/shared/FleetPageShell";
import { FeaturePending } from "@/components/shared/FeaturePending";

export default function SourcesPage() {
  return (
    <FleetPageShell
      title="Sources & streams"
      subtitle="Data sources and their derived streams across the fleet."
    >
      <FeaturePending surface="Sources & streams" eta="DIS APIs ~15 days" />
    </FleetPageShell>
  );
}
