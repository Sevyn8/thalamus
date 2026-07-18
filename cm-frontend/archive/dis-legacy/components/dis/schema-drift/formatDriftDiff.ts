import type { DriftEvent } from "@/types/dis";

// Phase 5c.4b: render a drift event's before→after as a tight inline
// string. v1 stays grep-able; if friendlier phrasing is ever asked for
// ("Column added: warehouse_zone (string, nullable)"), this is the
// single function to update.

function formatTypeNullable(
  type: string | null,
  nullable: boolean | null,
): string {
  if (type === null) return "(absent)";
  const nullabilityFragment =
    nullable === true ? " · nullable" : nullable === false ? " · required" : "";
  return `${type}${nullabilityFragment}`;
}

export function formatDriftDiff(event: DriftEvent): string {
  switch (event.event_type) {
    case "COLUMN_ADDED":
      return `(absent) → ${formatTypeNullable(event.after_type, event.after_nullable)}`;
    case "COLUMN_REMOVED":
      return `${formatTypeNullable(event.before_type, event.before_nullable)} → (removed)`;
    case "TYPE_CHANGED":
    case "NULLABILITY_CHANGED":
      return `${formatTypeNullable(event.before_type, event.before_nullable)} → ${formatTypeNullable(event.after_type, event.after_nullable)}`;
  }
}
