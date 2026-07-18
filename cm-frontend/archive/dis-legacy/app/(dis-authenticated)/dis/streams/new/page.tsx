// Phase 5n.4: DIS backend not shipped. Replace with real wizard
// when DIS APIs ship.

import { FleetPageShell } from "@/components/dis/shared/FleetPageShell";
import { FeaturePending } from "@/components/shared/FeaturePending";

export default function NewStreamPage() {
  return (
    <FleetPageShell title="New stream" subtitle="Create a new stream.">
      <FeaturePending surface="New stream" eta="DIS APIs ~15 days" />
    </FleetPageShell>
  );
}
