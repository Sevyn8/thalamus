"use client";

import { useMemo, useState } from "react";
import { AlertCircle, ChevronDown, ChevronRight, Loader2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { OrgNodePicker } from "@/components/org/OrgNodePicker";
import { useRoles } from "@/lib/hooks/use-roles";
import { useOrgTree } from "@/lib/hooks/use-org-nodes";
import type { OrgNodeTreeItem, RoleListItem } from "@/types/api";
import { cn } from "@/lib/utils";

// RoleAssignmentEditor: per-grant (role_id, org_node_id) editor used
// by the Edit and Create tenant-user modals.
// Fully controlled — `value` is the source of truth including
// partially-filled rows where role_id or org_node_id is "". The
// parent decides validity (see hasIncompleteRows / duplicate index
// helpers exported below) and gates its own Save button.
//
// TENANT-audience roles only: we read RoleListResponse.tenant_roles
// from useRoles() (server pre-groups by audience) and filter to
// status === "ACTIVE".
//
// Per-row UX: role <select> + collapsible OrgNodePicker for the
// anchor. Picker is shown when an anchor isn't picked yet; once
// picked, collapses to a button showing the anchor name. Org-tree
// fetch is shared across rows via TanStack Query dedup on the
// shared (tenantId, depth=2) key.

// Row shape used internally + by the editor. role_id="" / org_node_id=""
// represent partially-filled rows. Submit-time validation lives in
// the parent.
export type RoleAssignmentRow = {
  role_id: string;
  org_node_id: string;
};

export type RoleAssignmentEditorProps = {
  value: RoleAssignmentRow[];
  onChange: (next: RoleAssignmentRow[]) => void;
  tenantId: string;
  disabled?: boolean;
};

// Pure helpers a parent component can use to compute validity from
// `value` without reaching into the editor.
export function hasIncompleteRows(rows: RoleAssignmentRow[]): boolean {
  return rows.some((r) => r.role_id === "" || r.org_node_id === "");
}

export function findDuplicateIndexes(
  rows: RoleAssignmentRow[],
): Set<number> {
  const seen = new Map<string, number>();
  const dups = new Set<number>();
  rows.forEach((r, i) => {
    if (r.role_id === "" || r.org_node_id === "") return;
    const key = `${r.role_id}::${r.org_node_id}`;
    const firstIdx = seen.get(key);
    if (firstIdx !== undefined) {
      dups.add(firstIdx);
      dups.add(i);
    } else {
      seen.set(key, i);
    }
  });
  return dups;
}

export function RoleAssignmentEditor({
  value,
  onChange,
  tenantId,
  disabled,
}: RoleAssignmentEditorProps) {
  const rolesQuery = useRoles();
  // useOrgTree fetches the tree we use for org-node-name lookup
  // (the picker also calls it; TQ dedups on the shared key).
  const treeQuery = useOrgTree(tenantId);

  // Picker disclosure is purely cosmetic. Default: open for rows
  // without an anchor; closed for rows that have one.
  const [pickerOpenIds, setPickerOpenIds] = useState<Set<number>>(() => {
    const s = new Set<number>();
    value.forEach((r, i) => {
      if (r.org_node_id === "") s.add(i);
    });
    return s;
  });

  const tenantRoles: RoleListItem[] = useMemo(() => {
    const items = rolesQuery.data?.tenant_roles.items ?? [];
    return items.filter((r) => r.status === "ACTIVE");
  }, [rolesQuery.data]);

  const duplicateRowIndexes = useMemo(
    () => findDuplicateIndexes(value),
    [value],
  );

  // Walk the tree to find a node by id for the collapsed-state
  // anchor-name display. The tree may not be fully loaded for deep
  // anchors (depth=2 from useOrgTree default); in that case fall
  // back to the id. The picker itself owns lazy-loading.
  //
  // The synthetic tenant-root row (rendered by the shared picker via
  // synthesizeTenantRoot) lives outside `tree[]` — match it explicitly
  // so the collapsed state shows the tenant name rather than
  // "(anchor not in loaded tree)".
  function findOrgNodeName(nodeId: string): string {
    const treeData = treeQuery.data;
    if (!treeData) return "";
    if (nodeId === treeData.tenant_root_id) return treeData.tenant_name;
    function walk(nodes: OrgNodeTreeItem[]): string | null {
      for (const n of nodes) {
        if (n.id === nodeId) return n.name;
        const child = walk(n.children ?? []);
        if (child !== null) return child;
      }
      return null;
    }
    return walk(treeData.tree) ?? "";
  }

  function updateRow(idx: number, patch: Partial<RoleAssignmentRow>) {
    onChange(value.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  }

  function removeRow(idx: number) {
    onChange(value.filter((_, i) => i !== idx));
    setPickerOpenIds((prev) => {
      const next = new Set<number>();
      for (const i of prev) {
        if (i < idx) next.add(i);
        else if (i > idx) next.add(i - 1);
      }
      return next;
    });
  }

  function addRow() {
    const nextIdx = value.length;
    onChange([...value, { role_id: "", org_node_id: "" }]);
    setPickerOpenIds((prev) => {
      const next = new Set(prev);
      next.add(nextIdx);
      return next;
    });
  }

  function togglePicker(idx: number) {
    setPickerOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  }

  if (rolesQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 text-caption text-foreground-muted">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Loading roles…
      </div>
    );
  }

  if (rolesQuery.error) {
    return (
      <ErrorInline
        message="Could not load roles."
        onRetry={() => rolesQuery.refetch()}
      />
    );
  }

  if (tenantRoles.length === 0) {
    return (
      <p className="rounded-md border border-border bg-surface/40 p-3 text-caption text-foreground-muted">
        No tenant-audience roles available. Ask your administrator to create
        one before assigning users.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {value.length === 0 ? (
        <p className="text-caption text-foreground-muted">
          No role assignments. User will have no access.
        </p>
      ) : null}
      {value.map((row, idx) => {
        const isDup = duplicateRowIndexes.has(idx);
        const pickerOpen = pickerOpenIds.has(idx);
        const anchorLabel = row.org_node_id
          ? findOrgNodeName(row.org_node_id) || "(anchor not in loaded tree)"
          : "Pick an anchor…";
        return (
          <div
            key={idx}
            className={cn(
              "flex flex-col gap-2 rounded-md border p-3",
              isDup
                ? "border-[var(--danger-line)] bg-[var(--danger-bg)]/40 dark:bg-danger/5"
                : "border-border bg-surface/40",
            )}
          >
            <div className="flex items-start gap-2">
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <label className="text-xs font-medium text-foreground">
                  Role
                </label>
                <select
                  className={cn(
                    "h-9 w-full rounded-md border border-input bg-background px-2.5 text-sm",
                    "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
                    "dark:bg-input/30",
                  )}
                  value={row.role_id}
                  onChange={(e) => updateRow(idx, { role_id: e.target.value })}
                  disabled={disabled}
                >
                  <option value="">Select a role…</option>
                  {tenantRoles.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label="Remove role assignment"
                onClick={() => removeRow(idx)}
                disabled={disabled}
                className="mt-5 shrink-0"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-foreground">
                Anchor
              </label>
              <button
                type="button"
                onClick={() => togglePicker(idx)}
                disabled={disabled}
                className={cn(
                  "flex h-9 items-center justify-between rounded-md border border-input bg-background px-2.5 text-left text-sm",
                  "hover:bg-surface-raised",
                )}
              >
                <span className="truncate">{anchorLabel}</span>
                {pickerOpen ? (
                  <ChevronDown className="h-4 w-4 shrink-0 text-foreground-muted" />
                ) : (
                  <ChevronRight className="h-4 w-4 shrink-0 text-foreground-muted" />
                )}
              </button>
              {pickerOpen ? (
                <div className="max-h-44 overflow-auto rounded-md border border-border">
                  <OrgNodePicker
                    tenantId={tenantId}
                    selectedNodeId={row.org_node_id || null}
                    onSelect={(node: OrgNodeTreeItem) => {
                      updateRow(idx, { org_node_id: node.id });
                      togglePicker(idx);
                    }}
                  />
                </div>
              ) : null}
            </div>

            {isDup ? (
              <div
                role="alert"
                className="flex items-start gap-1.5 text-caption text-danger"
              >
                <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                  Duplicate of another row. Remove this row or pick a different
                  role/anchor combination.
                </span>
              </div>
            ) : null}
          </div>
        );
      })}

      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={addRow}
        disabled={disabled}
        className="self-start"
      >
        + Add role
      </Button>
    </div>
  );
}
