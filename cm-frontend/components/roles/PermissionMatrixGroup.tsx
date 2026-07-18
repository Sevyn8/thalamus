"use client";

import { ChevronDown, ChevronRight } from "lucide-react";

import { PermissionMatrixRow } from "./PermissionMatrixRow";
import type { PermissionMatrixRoleColumn, PermissionMatrixRow as Row } from "@/types/api";

// POSITION-ALIGNED ARRAY INVARIANT: row.cells[i] under roles[i].
// audienceIndices is the projection of full-roles indices to only
// the in-audience columns; row.cells[audienceIndices[k]] is the
// grant state for rolesInAudience[k]. Maintain alignment.

export type PermissionMatrixGroupProps = {
  resource: string;
  resourceLabel: string;
  rows: Row[];
  rolesInAudience: PermissionMatrixRoleColumn[];
  audienceIndices: number[];
  isExpanded: boolean;
  onToggle: () => void;
  // Module label rendered as a divider above the group header. Pass null to
  // suppress (used when the previous group shares this group's module).
  moduleDivider: string | null;
};

export function PermissionMatrixGroup({
  resource,
  resourceLabel,
  rows,
  rolesInAudience,
  audienceIndices,
  isExpanded,
  onToggle,
  moduleDivider,
}: PermissionMatrixGroupProps) {
  const colSpan = rolesInAudience.length + 1;
  const count = rows.length;

  return (
    <>
      {moduleDivider ? (
        <tr>
          <td
            colSpan={colSpan}
            className="border-t border-border bg-background px-3 pt-4 pb-1"
          >
            <span className="text-label text-foreground-subtle">{moduleDivider}</span>
          </td>
        </tr>
      ) : null}

      <tr className="hover:bg-surface-raised">
        <td colSpan={colSpan} className="bg-background p-0">
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={isExpanded}
            aria-controls={`matrix-group-${resource}`}
            className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors duration-150 ease-out hover:bg-surface-raised"
          >
            {isExpanded ? (
              <ChevronDown className="h-3.5 w-3.5 text-foreground-muted" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 text-foreground-muted" />
            )}
            <span className="text-body-strong">{resourceLabel}</span>
            <span className="text-caption text-foreground-muted">({count})</span>
          </button>
        </td>
      </tr>

      {isExpanded
        ? rows.map((row, i) => (
            <PermissionMatrixRow
              key={row.id}
              row={row}
              rolesInAudience={rolesInAudience}
              audienceIndices={audienceIndices}
              zebra={i % 2 === 1}
            />
          ))
        : null}
    </>
  );
}
