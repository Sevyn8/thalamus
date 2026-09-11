"use client";

import { ChevronDown, ChevronRight, Loader2, MoreHorizontal } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { OrgNodeTypeBadge } from "./OrgNodeTypeBadge";
import { OrgNodeTypeIcon } from "./OrgNodeTypeIcon";
import { useOrgNodeChildren, flattenChildPages } from "@/lib/hooks/use-org-nodes";
import { cn } from "@/lib/utils";
import type { OrgNodeTreeItem } from "@/types/api";

export type OrgNodeAction =
  | "edit"
  | "move"
  | "view-permissions"
  | "copy-code"
  | "delete";

export type OrgTreeRowProps = {
  node: OrgNodeTreeItem;
  tenantId: string;
  depth: number;
  ancestorGuides: boolean[];
  isLastChild: boolean;
  expanded: Set<string>;
  selectedId: string | null;
  onToggle: (id: string) => void;
  onClick: (node: OrgNodeTreeItem) => void;
  // Optional. When omitted (e.g. picker-mode consumers like OrgNodePicker),
  // the per-row kebab dropdown is not rendered — picker users should not
  // see edit/move/delete affordances. The /superadmin/org consumer
  // (OrgTreePane) passes a handler and gets the full dropdown.
  onAction?: (nodeId: string, action: OrgNodeAction) => void;
};

function AncestorColumn({ hasGuide }: { hasGuide: boolean }) {
  return (
    <div
      aria-hidden="true"
      className={cn("w-4 shrink-0 self-stretch", hasGuide && "border-l border-border")}
    />
  );
}

function OwnDepthGuide({ isLastChild }: { isLastChild: boolean }) {
  return (
    <div className="relative w-4 shrink-0 self-stretch" aria-hidden="true">
      <div className="absolute left-0 top-0 h-1/2 w-px bg-border" />
      {!isLastChild ? (
        <div className="absolute left-0 top-1/2 h-1/2 w-px bg-border" />
      ) : null}
      <div className="absolute left-0 top-1/2 h-px w-2 bg-border" />
    </div>
  );
}

export function OrgTreeRow({
  node,
  tenantId,
  depth,
  ancestorGuides,
  isLastChild,
  expanded,
  selectedId,
  onToggle,
  onClick,
  onAction,
}: OrgTreeRowProps) {
  const isExpanded = expanded.has(node.id);
  const isSelected = selectedId === node.id;

  // Lazy-load decision per the loaded_children enum (per backend's
  // schema doc):
  //   "all"     — every child is in node.children; no fetch needed
  //   "partial" — some present; more available at offset = node.children.length
  //   "none"    — either true leaf (has_children=false) or depth-cut
  //               node (has_children=true, fetch from offset 0)
  const initialChildren = node.children ?? [];
  const needsLazyFetch =
    node.has_children && node.loaded_children !== "all";
  // For "partial", continue fetching from where the initial tree left off.
  const initialOffset =
    node.loaded_children === "partial" ? initialChildren.length : 0;

  const childrenQuery = useOrgNodeChildren(
    tenantId,
    node.id,
    isExpanded && needsLazyFetch,
    initialOffset,
  );

  // Render-time merge: initial tree's children + lazy-fetched pages.
  // useInfiniteQuery is the single source of truth for accumulated
  // children — no separate Map state. TQ keys include tenantId so
  // cross-tenant queries are isolated.
  const lazyItems = flattenChildPages(childrenQuery.data);
  const visibleChildren = initialChildren.concat(lazyItems);

  const showLoadMoreButton = childrenQuery.hasNextPage === true;
  const isFetchingFirstPage = childrenQuery.isLoading;
  const isFetchingMore = childrenQuery.isFetchingNextPage;

  return (
    <li>
      <div
        className={cn(
          "group/row flex h-8 items-center transition-colors duration-150 ease-out",
          isSelected ? "bg-accent" : "hover:bg-surface-raised",
        )}
      >
        {ancestorGuides.map((g, i) => (
          <AncestorColumn key={i} hasGuide={g} />
        ))}
        {depth > 0 ? <OwnDepthGuide isLastChild={isLastChild} /> : null}

        {node.has_children ? (
          <button
            type="button"
            aria-label={isExpanded ? "Collapse" : "Expand"}
            aria-expanded={isExpanded}
            onClick={(e) => {
              e.stopPropagation();
              onToggle(node.id);
            }}
            className="flex h-4 w-4 shrink-0 items-center justify-center rounded text-foreground-muted transition-colors duration-150 hover:bg-accent hover:text-foreground"
          >
            {isExpanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
          </button>
        ) : (
          <span className="h-4 w-4 shrink-0" aria-hidden="true" />
        )}

        <button
          type="button"
          onClick={() => onClick(node)}
          className="flex min-w-0 flex-1 items-center gap-2 px-2 text-left"
        >
          <OrgNodeTypeIcon type={node.node_type} />
          <span className="truncate text-body">{node.name}</span>
          <OrgNodeTypeBadge type={node.node_type} />
        </button>

        {node.code ? (
          <code className="px-2 font-mono text-caption text-foreground-muted">
            {node.code}
          </code>
        ) : null}

        {onAction && node.node_type !== "TENANT" ? (
          // The synthetic TENANT root row is selectable but not editable
          // via this surface — tenant lifecycle lives on
          // /superadmin/tenants. Kebab hidden to avoid actions that
          // would 4xx against the org-tree write API.
          <div className="opacity-0 transition-opacity duration-150 group-hover/row:opacity-100 focus-within:opacity-100">
            <DropdownMenu>
              <DropdownMenuTrigger
                aria-label="Node actions"
                onClick={(e) => e.stopPropagation()}
                className="mr-2 flex h-6 w-6 items-center justify-center rounded text-foreground-muted hover:bg-accent hover:text-foreground"
              >
                <MoreHorizontal className="h-4 w-4" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => onAction(node.id, "edit")}>
                  Edit
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => onAction(node.id, "move")}>
                  Move
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => onAction(node.id, "view-permissions")}>
                  View permissions
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => onAction(node.id, "copy-code")}>
                  Copy code
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  variant="destructive"
                  onClick={() => onAction(node.id, "delete")}
                >
                  Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        ) : null}
      </div>

      {node.has_children && isExpanded ? (
        <ul role="group" className="animate-in fade-in-0 duration-150 ease-out">
          {isFetchingFirstPage ? (
            <li
              className="flex items-center gap-2 px-2 py-1 text-caption text-foreground-muted"
              aria-live="polite"
            >
              <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
              Loading…
            </li>
          ) : null}

          {visibleChildren.map((child, i) => {
            const childIsLast =
              i === visibleChildren.length - 1 && !showLoadMoreButton;
            const childAncestorGuides =
              depth === 0 ? [] : [...ancestorGuides, !isLastChild];
            return (
              <OrgTreeRow
                key={child.id}
                node={child}
                tenantId={tenantId}
                depth={depth + 1}
                ancestorGuides={childAncestorGuides}
                isLastChild={childIsLast}
                expanded={expanded}
                selectedId={selectedId}
                onToggle={onToggle}
                onClick={onClick}
                onAction={onAction}
              />
            );
          })}

          {showLoadMoreButton ? (
            <li
              className={cn(
                "flex items-center",
                depth === 0 ? "" : "ml-4",
              )}
            >
              {ancestorGuides.map((g, i) => (
                <AncestorColumn key={i} hasGuide={g} />
              ))}
              {depth > 0 ? <AncestorColumn hasGuide={!isLastChild} /> : null}
              <button
                type="button"
                onClick={() => childrenQuery.fetchNextPage()}
                disabled={isFetchingMore}
                className="my-1 ml-2 inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-2 py-0.5 text-caption text-foreground-muted hover:bg-surface-raised disabled:opacity-55"
              >
                {isFetchingMore ? (
                  <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                ) : null}
                +{node.child_count - visibleChildren.length} more
              </button>
            </li>
          ) : null}
        </ul>
      ) : null}
    </li>
  );
}
