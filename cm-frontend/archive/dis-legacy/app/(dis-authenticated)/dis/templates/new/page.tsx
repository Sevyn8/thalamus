// Phase 5n.4: DIS backend not shipped. Replace with real wizard
// when DIS APIs ship.

import { FleetPageShell } from "@/components/dis/shared/FleetPageShell";
import { FeaturePending } from "@/components/shared/FeaturePending";

export default function NewSuperTemplatePage() {
  return (
    <FleetPageShell
      title="New Super Template"
      subtitle="Create a new cross-tenant super template."
    >
      <FeaturePending surface="New Super Template" eta="DIS APIs ~15 days" />
    </FleetPageShell>
  );
}
