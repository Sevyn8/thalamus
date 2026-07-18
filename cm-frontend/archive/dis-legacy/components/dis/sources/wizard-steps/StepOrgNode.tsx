"use client";

import { OrgNodePicker } from "@/components/org/OrgNodePicker";
import type { OrgNodeTreeItem } from "@/types/api";

type Props = {
  tenantId: string;
  selectedNodeId: string | null;
  onSelect: (node: OrgNodeTreeItem) => void;
};

// Phase 5c.2b1 step 2: org-node assignment. Wraps OrgNodePicker (the
// 5b.3-deferred picker-mode extraction) with required-validation
// helper text. tenantId comes from persona; this wizard is Tenant-only
// per 5c.2a, so persona.tenantId is always present at this step.
export function StepOrgNode({ tenantId, selectedNodeId, onSelect }: Props) {
  return (
    <div className="flex flex-col gap-3">
      <p className="text-caption text-muted-foreground">
        Choose where in your organisation this source belongs. Sources scope to
        a single org node in v1; multi-node attachment lands in v2.
      </p>
      <OrgNodePicker
        tenantId={tenantId}
        selectedNodeId={selectedNodeId}
        onSelect={onSelect}
      />
      {!selectedNodeId ? (
        <p className="text-caption text-muted-foreground">
          Pick a node to continue.
        </p>
      ) : null}
    </div>
  );
}
