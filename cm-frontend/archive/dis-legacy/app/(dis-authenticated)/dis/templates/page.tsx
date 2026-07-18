// Phase 5n.4: DIS backend not shipped. Replace with real hook +
// render when DIS APIs ship.

import { FleetPageShell } from "@/components/dis/shared/FleetPageShell";
import { FeaturePending } from "@/components/shared/FeaturePending";

export default function TemplatesPage() {
  return (
    <FleetPageShell
      title="Templates"
      subtitle="Super templates for cross-tenant pipeline configurations."
    >
      <FeaturePending surface="Templates" eta="DIS APIs ~15 days" />
    </FleetPageShell>
  );
}
