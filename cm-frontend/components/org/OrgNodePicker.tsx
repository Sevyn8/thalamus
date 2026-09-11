"use client";

import { useMemo, useState } from "react";

import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { OrgTreeRow } from "./OrgTreeRow";
import { useOrgTree } from "@/lib/hooks/use-org-nodes";
import { synthesizeTenantRoot } from "@/lib/org-nodes/synthesize-tenant-root";
import type { OrgNodeTreeItem } from "@/types/api";

// Picker-mode of OrgTree, extracted for the source-create wizard's
// org-node assignment step, the concrete consumer that drives the API
// shape.
//
// Composes OrgTreeRow with onAction omitted (hiding the kebab/edit
// affordances — picker users don't manage nodes, they pick one) and
// reuses Ithina's useOrgTree(tenantId) hook so the data source is the
// same as /superadmin/org. Selection is driven via OrgTreeRow's
// existing selectedId + onClick(node) props.
//
// Always renders the synthetic tenant-root row at the top (via
// synthesizeTenantRoot) so anchor-required surfaces always have at
// least one selectable option, even for tenants whose org tree is
// empty beyond the root.

export type OrgNodePickerProps = {
  tenantId: string;
  selectedNodeId: string | null;
  onSelect: (node: OrgNodeTreeItem) => void;
};

export function OrgNodePicker({
  tenantId,
  selectedNodeId,
  onSelect,
}: OrgNodePickerProps) {
  const tree = useOrgTree(tenantId);
  const tenantRoot = useMemo(
    () => synthesizeTenantRoot(tree.data),
    [tree.data],
  );
  const roots = useMemo<OrgNodeTreeItem[]>(
    () => (tenantRoot ? [tenantRoot] : []),
    [tenantRoot],
  );

  // User toggle overrides; default expansion = depth 0 + 1.
  // Mirror OrgTreePane's expansion logic.
  const [userToggled, setUserToggled] = useState<Map<string, boolean>>(new Map());

  const expanded = useMemo(() => {
    const set = new Set<string>();
    function walk(nodes: OrgNodeTreeItem[], depth: number) {
      for (const n of nodes) {
        const userChoice = userToggled.get(n.id);
        const shouldExpand = userChoice !== undefined ? userChoice : depth <= 1;
        if (shouldExpand) set.add(n.id);
        const childList = n.children ?? [];
        if (childList.length > 0) walk(childList, depth + 1);
      }
    }
    walk(roots, 0);
    return set;
  }, [roots, userToggled]);

  function toggle(id: string) {
    setUserToggled((prev) => {
      const next = new Map(prev);
      const currentExpanded = expanded.has(id);
      next.set(id, !currentExpanded);
      return next;
    });
  }

  if (tree.isLoading) {
    return (
      <div className="flex flex-col gap-2">
        <Skeleton variant="row" count={6} />
      </div>
    );
  }

  if (tree.error) {
    return (
      <ErrorInline
        message="Could not load organization tree."
        onRetry={() => tree.refetch()}
      />
    );
  }

  return (
    <ul className="flex flex-col rounded-md border border-border bg-card/30 p-2">
      {roots.map((root, i) => {
        const isLastRoot = i === roots.length - 1;
        return (
          <OrgTreeRow
            key={root.id}
            node={root}
            tenantId={tenantId}
            depth={0}
            ancestorGuides={[]}
            isLastChild={isLastRoot}
            expanded={expanded}
            selectedId={selectedNodeId}
            onToggle={toggle}
            onClick={onSelect}
          />
        );
      })}
    </ul>
  );
}
