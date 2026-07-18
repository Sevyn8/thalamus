// Phase 5n.4: DIS backend not shipped. Replace with real hook +
// render when DIS APIs ship.

import { FleetPageShell } from "@/components/dis/shared/FleetPageShell";
import { FeaturePending } from "@/components/shared/FeaturePending";

export default function SchemaDriftPage() {
  return (
    <FleetPageShell
      title="Schema drift"
      subtitle="Schema drift events across the fleet."
    >
      <FeaturePending surface="Schema drift" eta="DIS APIs ~15 days" />
    </FleetPageShell>
  );
}
