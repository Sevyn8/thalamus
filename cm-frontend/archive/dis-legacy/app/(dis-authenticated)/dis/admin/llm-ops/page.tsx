// Phase 5n.4: DIS backend not shipped. Replace with real hook +
// render when DIS APIs ship.

import { FleetPageShell } from "@/components/dis/shared/FleetPageShell";
import { FeaturePending } from "@/components/shared/FeaturePending";

export default function LlmOpsPage() {
  return (
    <FleetPageShell
      title="LLM operations"
      subtitle="Model usage, cost, and quality metrics across tenants."
    >
      <FeaturePending surface="LLM operations" eta="DIS APIs ~15 days" />
    </FleetPageShell>
  );
}
