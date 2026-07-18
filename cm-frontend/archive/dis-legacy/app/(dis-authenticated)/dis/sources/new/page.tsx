// Phase 5n.4: DIS backend not shipped. Replace with real wizard
// when DIS APIs ship.

import { FleetPageShell } from "@/components/dis/shared/FleetPageShell";
import { FeaturePending } from "@/components/shared/FeaturePending";

export default function NewSourcePage() {
  return (
    <FleetPageShell title="New source" subtitle="Create a new data source.">
      <FeaturePending surface="New source" eta="DIS APIs ~15 days" />
    </FleetPageShell>
  );
}
