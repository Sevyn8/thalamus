// Phase 5n.4: DIS backend not shipped. Replace with real hook +
// render when DIS APIs ship.

import { FleetPageShell } from "@/components/dis/shared/FleetPageShell";
import { FeaturePending } from "@/components/shared/FeaturePending";

export default function DashboardsPage() {
  return (
    <FleetPageShell
      title="Dashboards"
      subtitle="Tenant-scoped DIS operational dashboard."
    >
      <FeaturePending surface="DIS Dashboards" eta="DIS APIs ~15 days" />
    </FleetPageShell>
  );
}
