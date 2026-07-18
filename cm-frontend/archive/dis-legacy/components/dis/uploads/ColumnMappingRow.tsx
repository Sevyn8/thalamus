"use client";

import { EyeOff, Eye } from "lucide-react";

import { Chip, type Tone } from "@/components/shared/Chips";
import { Button } from "@/components/ui/button";
import { redact, shouldRedact } from "@/lib/dis/pii";
import { cn } from "@/lib/utils";
import type { CanonicalSchemaDomain, ColumnMapping } from "@/types/dis";

type Props = {
  column: ColumnMapping;
  schema: CanonicalSchemaDomain[];
  // Read-only mode renders the row without override dropdown / ignore
  // toggle (used for non-PENDING_REVIEW upload statuses).
  readOnly: boolean;
  // Draft state, owned by MappingReviewView. null = not yet mapped,
  // non-null = canonical_field_id chosen.
  draftMapping: string | null;
  draftIgnored: boolean;
  onMappingChange: (canonicalFieldId: string | null) => void;
  onToggleIgnored: () => void;
};

// Phase 5c.1b A8 amendment: high >= 0.85, medium 0.6..0.85, low < 0.6.
// Reasoning: red was triggering too easily on plausible 0.65-ish
// confidences. Reserve red for genuinely uncertain proposals where
// the tenant must override.
function confidenceTone(c: number): Tone {
  if (c >= 0.85) return "green";
  if (c >= 0.6) return "amber";
  return "red";
}

function confidenceLabel(c: number): string {
  if (c >= 0.85) return "High";
  if (c >= 0.6) return "Medium";
  return "Low";
}

export function ColumnMappingRow({
  column,
  schema,
  readOnly,
  draftMapping,
  draftIgnored,
  onMappingChange,
  onToggleIgnored,
}: Props) {
  const proposal = column.llm_proposal;
  // Inline samples in this row are redacted by default using the same
  // policy as SampleRowsTable: heuristic match on the value OR the
  // canonical-schema field's pii flag (when a mapping is in place).
  // Unlike SampleRowsTable, no per-row "View raw" affordance here —
  // the column row is a mapping-decision UI; raw values for
  // investigation belong to the sample-rows section below.
  const effectiveMapping = draftMapping ?? column.current_mapping;

  return (
    <li
      className={cn(
        "grid grid-cols-12 items-start gap-4 border-b border-border px-6 py-4 last:border-b-0",
        draftIgnored && "opacity-60",
      )}
    >
      <div className="col-span-3 flex flex-col gap-1 min-w-0">
        <span className="font-mono text-sm font-medium truncate" title={column.source_column}>
          {column.source_column}
        </span>
        <div className="flex flex-col gap-0.5">
          {column.sample_values.slice(0, 3).map((v, i) => {
            const display = shouldRedact(v, effectiveMapping, schema) ? redact(v) : v;
            return (
              <span
                key={i}
                className="truncate text-xs text-muted-foreground"
                title={display}
              >
                {display}
              </span>
            );
          })}
        </div>
      </div>

      {proposal ? (
        <div className="col-span-3 flex flex-col gap-1.5 min-w-0">
          <div className="flex items-center gap-2">
            <Chip tone={confidenceTone(proposal.confidence)}>
              {confidenceLabel(proposal.confidence)} ({Math.round(proposal.confidence * 100)}%)
            </Chip>
          </div>
          <span
            className="truncate text-xs text-muted-foreground"
            title={proposal.canonical_field_id}
          >
            Suggests <span className="font-mono">{proposal.canonical_field_id}</span>
          </span>
        </div>
      ) : null}

      <div
        className={cn(
          "flex flex-col gap-1.5 min-w-0",
          proposal ? "col-span-4" : "col-span-7",
        )}
      >
        {readOnly ? (
          <span className="text-sm">
            {column.canonical_field_label ?? (
              <span className="text-muted-foreground italic">
                {column.ignored ? "Ignored" : "Not mapped"}
              </span>
            )}
          </span>
        ) : (
          <select
            aria-label={`Canonical field for ${column.source_column}`}
            disabled={draftIgnored}
            value={draftMapping ?? ""}
            onChange={(e) => onMappingChange(e.target.value === "" ? null : e.target.value)}
            className={cn(
              "h-9 w-full rounded-md border border-input bg-background px-2.5 py-1 text-sm",
              "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
              "disabled:cursor-not-allowed disabled:opacity-50 dark:bg-input/30",
            )}
          >
            <option value="">Pick a canonical field…</option>
            {schema.map((d) => (
              <optgroup key={d.id} label={d.name}>
                {d.fields.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        )}
      </div>

      <div className="col-span-2 flex items-center justify-end">
        {readOnly ? null : (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onToggleIgnored}
            aria-pressed={draftIgnored}
          >
            {draftIgnored ? (
              <>
                <Eye className="h-4 w-4" />
                Unignore
              </>
            ) : (
              <>
                <EyeOff className="h-4 w-4" />
                Ignore
              </>
            )}
          </Button>
        )}
      </div>
    </li>
  );
}
