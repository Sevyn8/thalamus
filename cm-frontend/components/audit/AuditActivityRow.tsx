"use client";

import { Chip, type Tone } from "@/components/shared/Chips";
import { TableCell, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import type {
  AuditActivityListItem,
  AuditResultType,
} from "@/lib/api/audit";

// Phase 5h.1 + 5i.1: result tone now drives from the `result_type`
// enum (added to the list shape in Step 6.16.7), not the localized
// label string. Map covers the 6 known enum values; unknown values
// (e.g. a future addition) fall back to grey.
const RESULT_TONE_BY_TYPE: Record<AuditResultType, Tone> = {
  SUCCESS: "green",
  PERMISSION_DENIED: "red",
  VALIDATION_FAILED: "amber",
  CONFLICT: "amber",
  INTEGRITY_VIOLATION: "red",
  INTERNAL_ERROR: "red",
};

export function resultTone(resultType: AuditResultType | null | undefined): Tone {
  if (!resultType) return "grey";
  return RESULT_TONE_BY_TYPE[resultType] ?? "grey";
}

// Phase 5i.1: resource_type is an open string vocabulary (per the
// backend schema doc); these 6 values are the current emitters. Tones
// chosen to disambiguate visually in a multi-row table without
// implying severity. Unknown values fall back to grey.
const RESOURCE_TYPE_TONE: Record<string, Tone> = {
  TENANT: "blue",
  TENANT_USER: "violet",
  ROLE: "teal",
  MODULE_ACCESS: "amber",
  ORG_NODE: "purple",
  STORE: "green",
};

export function resourceTypeTone(resourceType: string | null | undefined): Tone {
  if (!resourceType) return "grey";
  return RESOURCE_TYPE_TONE[resourceType] ?? "grey";
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export type AuditActivityRowProps = {
  row: AuditActivityListItem;
  showScope: boolean;
  showTenant: boolean;
  onSelect: (id: string) => void;
};

export function AuditActivityRow({
  row,
  showScope,
  showTenant,
  onSelect,
}: AuditActivityRowProps) {
  return (
    <TableRow
      onClick={() => onSelect(row.id)}
      className={cn(
        "cursor-pointer transition-colors duration-150 ease-out",
        "hover:bg-surface-raised",
      )}
    >
      <TableCell
        className="whitespace-nowrap font-mono text-caption text-foreground-muted"
        title={row.timestamp}
      >
        {formatTimestamp(row.timestamp)}
      </TableCell>
      <TableCell className="text-body">{row.actor_display_name}</TableCell>
      <TableCell className="text-body">{row.action_label}</TableCell>
      <TableCell className="text-body text-foreground-muted">
        {row.resource_label ?? "—"}
      </TableCell>
      <TableCell>
        <Chip tone={resourceTypeTone(row.resource_type)}>
          {row.resource_type}
        </Chip>
      </TableCell>
      <TableCell>
        <Chip tone={resultTone(row.result_type)}>{row.result_label}</Chip>
      </TableCell>
      {showScope ? (
        <TableCell>
          <Chip tone={row.scope === "PLATFORM" ? "blue" : "grey"}>
            {row.scope}
          </Chip>
        </TableCell>
      ) : null}
      {showTenant ? (
        <TableCell className="text-body text-foreground-muted">
          {row.tenant_name ?? "—"}
        </TableCell>
      ) : null}
    </TableRow>
  );
}
