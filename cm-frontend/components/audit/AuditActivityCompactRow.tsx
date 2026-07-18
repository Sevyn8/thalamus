"use client";

import { formatDistanceToNow } from "date-fns";

import { Chip } from "@/components/shared/Chips";
import { resourceTypeTone, resultTone } from "./AuditActivityRow";
import { cn } from "@/lib/utils";
import type { AuditActivityListItem } from "@/lib/api/audit";

// Phase 5i.1: compact `<li>` companion to AuditActivityRow. Used in
// non-table contexts — RecentActivityPanel on the dashboard and the
// "Recent activity" sub-section inside user detail drawers. Renders
// the `what` field (a one-line backend-localized summary added in
// Step 6.16.7) as the row's primary label and pairs it with the
// resource-type and result chips. Click routes to the consumer's
// chosen handler (e.g. open audit detail drawer, or `router.push`).
//
// Separate component (not a `variant` prop on AuditActivityRow)
// because the two surfaces return structurally different DOM —
// <TableRow> vs <li> — and prop-driven branching across that boundary
// would force consumers to know which DOM shell they're inside.

export type AuditActivityCompactRowProps = {
  row: AuditActivityListItem;
  onClick: () => void;
};

export function AuditActivityCompactRow({
  row,
  onClick,
}: AuditActivityCompactRowProps) {
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className={cn(
          "flex w-full items-start gap-3 rounded-md px-2 py-2 text-left text-sm",
          "transition-colors duration-150 ease-out hover:bg-surface-raised",
        )}
      >
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="truncate font-medium">{row.what}</span>
          <span className="text-caption text-foreground-muted">
            {formatDistanceToNow(new Date(row.timestamp), { addSuffix: true })}
            <span className="mx-1.5">·</span>
            {row.actor_display_name}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Chip tone={resourceTypeTone(row.resource_type)}>
            {row.resource_type}
          </Chip>
          <Chip tone={resultTone(row.result_type)}>{row.result_label}</Chip>
        </div>
      </button>
    </li>
  );
}
