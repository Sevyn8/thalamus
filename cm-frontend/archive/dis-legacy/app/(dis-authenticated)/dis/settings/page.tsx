// Phase 5n.4: DIS backend not shipped. Replace with real hook +
// render when DIS APIs ship.

import { FleetPageShell } from "@/components/dis/shared/FleetPageShell";
import { FeaturePending } from "@/components/shared/FeaturePending";

export default function DisSettingsPage() {
  return (
    <FleetPageShell
      title="DIS settings"
      subtitle="Per-tenant ingestion configuration."
    >
      <FeaturePending surface="DIS settings" eta="DIS APIs ~15 days" />
    </FleetPageShell>
  );
}
