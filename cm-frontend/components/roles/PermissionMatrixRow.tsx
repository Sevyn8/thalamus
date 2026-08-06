"use client";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { PermissionMatrixRoleColumn, PermissionMatrixRow as Row } from "@/types/api";

// POSITION-ALIGNED ARRAY INVARIANT: row.cells[audienceIndices[k]] is
// the grant state for rolesInAudience[k]. Project full-roles indices
// to in-audience indices via audienceIndices. Maintain alignment.

export type PermissionMatrixRowProps = {
  row: Row;
  rolesInAudience: PermissionMatrixRoleColumn[];
  audienceIndices: number[];
  // Stripe row backgrounds for vertical scanability. Caller passes the row
  // index within its group so we can alternate.
  zebra: boolean;
};

export function PermissionMatrixRow({
  row,
  rolesInAudience,
  audienceIndices,
  zebra,
}: PermissionMatrixRowProps) {
  return (
    <tr className={cn("group/matrix-row hover:bg-surface-raised", zebra && "bg-muted/20")}>
      <th
        scope="row"
        className={cn(
          "sticky left-0 z-10 h-8 min-w-[240px] max-w-[240px] border-b border-r border-border px-3 text-left",
          zebra ? "bg-muted/20" : "bg-card",
          "group-hover/matrix-row:bg-surface-raised",
        )}
      >
        <span className="text-body">{row.action_label}</span>
        <span className="px-1 text-foreground-muted">·</span>
        <span className="text-caption text-foreground-muted">{row.scope_label}</span>
      </th>
      {rolesInAudience.map((role, k) => {
        const granted = row.cells[audienceIndices[k]!] === true;
        // Derive code from the row's enum fields (composed):
        // module.resource.action.scope. Same shape as backend's
        // /permissions response.code field.
        const code = `${row.module}.${row.resource}.${row.action}.${row.scope}`;
        return (
          <td
            key={role.id}
            className="h-8 min-w-[80px] border-b border-border p-0 text-center"
            aria-label={
              granted ? `${role.name} grants ${code}` : `${role.name} does not grant ${code}`
            }
          >
            <Tooltip>
              <TooltipTrigger
                render={
                  <div
                    className="flex h-8 w-full items-center justify-center"
                    aria-hidden="true"
                  />
                }
              >
                {granted ? (
                  <span className="h-1.5 w-1.5 rounded-full bg-success" />
                ) : null}
              </TooltipTrigger>
              <TooltipContent>{code}</TooltipContent>
            </Tooltip>
          </td>
        );
      })}
    </tr>
  );
}
