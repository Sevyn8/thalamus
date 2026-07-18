// Phase 5n.4: DIS backend not shipped. Replace with real hook +
// render when DIS APIs ship.

import { FleetPageShell } from "@/components/dis/shared/FleetPageShell";
import { FeaturePending } from "@/components/shared/FeaturePending";

export default function CanonicalSchemaPage() {
  return (
    <FleetPageShell
      title="Canonical schema"
      subtitle="Canonical field reference across domains and entities."
    >
      <FeaturePending surface="Canonical schema" eta="DIS APIs ~15 days" />
    </FleetPageShell>
  );
}
