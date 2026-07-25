"use client";

import { useMemo, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle } from "lucide-react";

import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { EmptyState } from "@/components/shared/EmptyState";
import { comingInV1 } from "@/components/shared/ComingInV1Toast";
import { CreateOrgNodeModal } from "./CreateOrgNodeModal";
import { EditOrgNodeModal } from "./EditOrgNodeModal";
import { OrgTreeRow, type OrgNodeAction } from "./OrgTreeRow";
import { useOrgTree } from "@/lib/hooks/use-org-nodes";
import { useCanDo } from "@/lib/auth/use-me-can-do";
import { synthesizeTenantRoot } from "@/lib/org-nodes/synthesize-tenant-root";
import { cn } from "@/lib/utils";
import type { OrgNodeTreeItem } from "@/types/api";

export type OrgTreePaneProps = {
  tenantId: string | null;
  selectedNodeId: string | null;
  selectedNode: OrgNodeTreeItem | null;
  onNodeSelect: (node: OrgNodeTreeItem) => void;
};

// Backend's tree is already nested (OrgNodeTreeItem.children is
// recursive), so no flat-to-nested assembly. The component just
// renders directly. Lazy-fetches and "+N more" pagination are owned
// by OrgTreeRow via useInfiniteQuery — TQ is the single source of
// truth for accumulated children, and the OrgTreePane re-keys on
// tenantId so collapse/expand state resets cleanly across tenant
// switches without coordinating a separate accumulator Map.
export function OrgTreePane({
  tenantId,
  selectedNodeId,
  selectedNode,
  onNodeSelect,
}: OrgTreePaneProps) {
  const tree = useOrgTree(tenantId ?? "");

  // Phase 5g.1.4: synthesize a TENANT-typed root row so the tenant
  // itself is selectable in the hierarchy. Backend's org-tree response
  // surfaces HQ as the first concrete node and exposes the tenant
  // identity only as siblings of `tree[]` (tenant_root_id +
  // tenant_root_code from Step 6.21.1). The synthetic row is
  // read-only from the org-tree surface (kebab actions hidden in
  // OrgTreeRow when node_type === "TENANT") — tenant lifecycle lives
  // on /superadmin/tenants.
  //
  // Phase 5i.2 (2026-05-25): synthesis routed through the shared
  // synthesizeTenantRoot helper. Two behavior changes fall out:
  //  (a) synthetic row's `id` is now `tenant_root_id` (the org_nodes
  //      table UUID) rather than `tenant_id` (tenants table UUID) —
  //      this corrects a latent mismatch where the synthetic row's id
  //      was the wrong UUID for "Add child node" POSTs against
  //      /tenants/{id}/org-tree, which expects a parent_id from
  //      org_nodes. Resolves the Finding #46 follow-up.
  //
  // Slice 8: this helper feeds the POPULATED-tree render only. The
  // empty (root-only) tenant case is handled by its own branch below
  // (header + "Add the first node" CTA), not by rendering the synthetic
  // row, so an empty tenant is no longer a dead end.
  const tenantRoot = useMemo(
    () => synthesizeTenantRoot(tree.data),
    [tree.data],
  );
  const roots = useMemo<OrgNodeTreeItem[]>(
    () => (tenantRoot ? [tenantRoot] : []),
    [tenantRoot],
  );

  // Single permission tuple gates POST + PATCH (Step 6.13 LD9 collapse;
  // matches the Stores pattern from Finding #32). PLATFORM passes via
  // GLOBAL→TENANT cascade; OWNER via direct TENANT grant. No
  // target_anchor: backend expects an ltree path, not a UUID — see
  // lib/api/me.ts for the contract.
  const canManageOrgTree = useCanDo(
    "ADMIN",
    "ORG_NODES",
    "CONFIGURE",
    "TENANT",
  );
  const canWrite = canManageOrgTree.data?.allowed !== false;

  // User toggle overrides. Default expansion (depth 0 + 1 visible)
  // computed from `roots` per render; users override per-node here.
  const [userToggled, setUserToggled] = useState<Map<string, boolean>>(new Map());

  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<OrgNodeTreeItem | null>(null);
  const [editFocusReparent, setEditFocusReparent] = useState(false);

  const expanded = useMemo(() => {
    const set = new Set<string>();
    function walk(nodes: OrgNodeTreeItem[], depth: number) {
      for (const n of nodes) {
        const userChoice = userToggled.get(n.id);
        // Default-expand depths 0-2 to preserve "two levels visible"
        // UX (tenant + HQ + region/country). The synthetic TENANT row
        // added in 5g.1.4 shifted everything down one level; the
        // threshold compensates so the user-visible shape is unchanged.
        const shouldExpand = userChoice !== undefined ? userChoice : depth <= 2;
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

  function findNode(id: string): OrgNodeTreeItem | null {
    function walk(nodes: OrgNodeTreeItem[]): OrgNodeTreeItem | null {
      for (const n of nodes) {
        if (n.id === id) return n;
        const hit = walk(n.children ?? []);
        if (hit) return hit;
      }
      return null;
    }
    return walk(roots);
  }

  function handleAction(nodeId: string, action: OrgNodeAction) {
    const node = findNode(nodeId);
    if (!node) return;
    switch (action) {
      case "edit": {
        setEditTarget(node);
        setEditFocusReparent(false);
        return;
      }
      case "move": {
        setEditTarget(node);
        setEditFocusReparent(true);
        return;
      }
      case "copy-code": {
        void navigator.clipboard.writeText(node.code);
        toast.success("Code copied");
        return;
      }
      case "view-permissions": {
        comingInV1("View node permissions");
        return;
      }
      case "delete": {
        comingInV1("Delete node");
        return;
      }
    }
  }

  if (!tenantId) {
    return (
      <EmptyState
        title="Select a tenant on the left"
        body="Choose a tenant to view its organisation."
      />
    );
  }

  if (tree.isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton variant="rect" />
        <Skeleton variant="row" count={8} />
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

  const data = tree.data;
  if (!data) {
    return (
      <EmptyState
        title="No organization data"
        body="Could not load this tenant's organisation."
      />
    );
  }

  // Slice 8: root-only tenants (wizard-created tenants have just their
  // TENANT root, which the tree endpoint filters out, so tree is empty)
  // are no longer a dead end. Render the tenant header with "+ Add node"
  // plus a first-node CTA that opens the create modal in parentless mode
  // (HQ preselected, parent omitted; the backend resolves it to the
  // tenant root). Populated trees fall through to the normal render.
  if (data.tree.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        <header className="flex items-center justify-between gap-3 border-b border-border pb-4">
          <div className="flex flex-col gap-1">
            <h2 className="text-heading">{data.tenant_name}</h2>
            <p className="text-caption text-foreground-muted">
              No org structure yet
            </p>
          </div>
          {canWrite ? (
            <button
              type="button"
              onClick={() => setCreateOpen(true)}
              className="inline-flex h-8 items-center rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
            >
              + Add node
            </button>
          ) : null}
        </header>

        <EmptyState
          title="No org structure yet"
          body="Add the first node to start building this tenant's organisation."
          action={
            canWrite
              ? { label: "Add the first node", onClick: () => setCreateOpen(true) }
              : undefined
          }
        />

        {canWrite ? (
          <CreateOrgNodeModal
            open={createOpen}
            onOpenChange={setCreateOpen}
            tenantId={tenantId}
            defaultParent={null}
            parentless
          />
        ) : null}
      </div>
    );
  }

  const stats = data.stats;

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-center justify-between gap-3 border-b border-border pb-4">
        <div className="flex flex-col gap-1">
          <h2 className="text-heading">{data.tenant_name}</h2>
          <p className="text-caption text-foreground-muted">
            {stats.total_nodes.toLocaleString()} nodes ·{" "}
            {stats.stores.toLocaleString()} stores ·{" "}
            {stats.regions.toLocaleString()} regions
          </p>
        </div>
        {canWrite ? (
          <button
            type="button"
            onClick={() => setCreateOpen(true)}
            className="inline-flex h-8 items-center rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            + Add node
          </button>
        ) : null}
      </header>

      {stats.truncated ? (
        <div
          className={cn(
            "flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-caption text-amber-700",
            "dark:text-amber-200",
          )}
          role="status"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>
            <span className="font-medium">Partial tree shown.</span>{" "}
            This tenant&apos;s org structure exceeds the 1,000-node response cap.
            Drill into specific nodes to load deeper levels.
          </span>
        </div>
      ) : null}

      <ul className="flex flex-col">
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
              onClick={onNodeSelect}
              onAction={canWrite ? handleAction : undefined}
            />
          );
        })}
      </ul>

      {canWrite ? (
        <CreateOrgNodeModal
          open={createOpen}
          onOpenChange={setCreateOpen}
          tenantId={tenantId}
          defaultParent={selectedNode ?? roots[0] ?? null}
        />
      ) : null}

      {canWrite && editTarget ? (
        <EditOrgNodeModal
          open={!!editTarget}
          onOpenChange={(next) => {
            if (!next) setEditTarget(null);
          }}
          tenantId={tenantId}
          node={editTarget}
          focusReparent={editFocusReparent}
        />
      ) : null}
    </div>
  );
}
