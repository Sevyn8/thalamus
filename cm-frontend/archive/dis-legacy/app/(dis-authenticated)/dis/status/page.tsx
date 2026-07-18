// Phase 5n.4: DIS backend not shipped. Replace with real hook +
// render when DIS APIs ship.

import { FleetPageShell } from "@/components/dis/shared/FleetPageShell";
import { FeaturePending } from "@/components/shared/FeaturePending";

export default function StatusPage() {
  return (
    <FleetPageShell
      title="Status"
      subtitle="DIS system status across services."
    >
      <FeaturePending surface="System status" eta="DIS APIs ~15 days" />
    </FleetPageShell>
  );
}
