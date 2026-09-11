"use client";

import {
  Building,
  Building2,
  Globe,
  Map,
  Package,
  Store,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Drawer } from "@/components/shared/Drawer";
import { StatusChip } from "@/components/shared/Chips";
import { comingInV1 } from "@/components/shared/ComingInV1Toast";
import { cn } from "@/lib/utils";
import type { OrgNodeTreeItem, OrgNodeType } from "@/types/api";

const ICON_BY_TYPE: Record<OrgNodeType, React.ComponentType<{ className?: string }>> = {
  HQ: Building,
  REGION: Map,
  STORE: Store,
  BUSINESS_UNIT: Building2,
  COUNTRY: Globe,
  DEPARTMENT: Package,
  TENANT: Building,
};

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function MetadataRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">{children}</span>
    </div>
  );
}

// Backend's OrgNodeTreeItem omits parent_id / ltree_path / depth, so
// the drawer can't render a path breadcrumb without threading parent
// context from the tree-walk caller. There is no breadcrumb section;
// immediate-children counts stand in for it. If breadcrumb UX becomes
// load-bearing, thread ancestor names down via prop or resolve via
// tree-walk in the caller.
function Body({ node }: { node: OrgNodeTreeItem }) {
  const Icon = ICON_BY_TYPE[node.node_type];

  return (
    <div className="flex flex-col gap-4 pt-2">
      <div className="flex items-center gap-3">
        <span
          className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground",
          )}
          aria-hidden="true"
        >
          <Icon className="h-5 w-5" />
        </span>
        <div className="flex min-w-0 flex-col">
          <div className="truncate font-medium">{node.name}</div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="outline" className="text-[10px] uppercase tracking-wide">
              {node.node_type}
            </Badge>
            {node.code ? <code>{node.code}</code> : null}
          </div>
        </div>
      </div>

      <Separator />

      <div className="flex flex-col gap-2">
        <div className="text-label text-muted-foreground">
          Children
        </div>
        <div className="text-sm">
          {node.has_children
            ? `${node.child_count.toLocaleString()} direct ${
                node.child_count === 1 ? "child" : "children"
              }`
            : "Leaf node (no children)"}
        </div>
      </div>

      <Separator />

      <div className="flex flex-col gap-1">
        <div className="text-label text-muted-foreground">
          Metadata
        </div>
        <div className="divide-y divide-border">
          <MetadataRow label="Status">
            <StatusChip status={node.status} />
          </MetadataRow>
          <MetadataRow label="Created">{formatDate(node.created_at)}</MetadataRow>
          <MetadataRow label="Last updated">{formatDate(node.updated_at)}</MetadataRow>
        </div>
      </div>
    </div>
  );
}

export type NodeDetailDrawerProps = {
  node: OrgNodeTreeItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function NodeDetailDrawer({
  node,
  open,
  onOpenChange,
}: NodeDetailDrawerProps) {
  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      width="lg"
      title={node?.name ?? "Node"}
      subtitle={
        node ? `${node.node_type}${node.code ? ` · ${node.code}` : ""}` : undefined
      }
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button variant="destructive" onClick={() => comingInV1("Delete node")}>
            Delete
          </Button>
          <Button variant="outline" onClick={() => comingInV1("Add child node")}>
            Add child
          </Button>
          <Button onClick={() => comingInV1("Edit node")}>Edit</Button>
        </div>
      }
    >
      {node ? <Body node={node} /> : null}
    </Drawer>
  );
}
