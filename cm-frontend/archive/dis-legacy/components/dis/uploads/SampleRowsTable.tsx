"use client";

import { useState } from "react";
import { Eye, EyeOff, ShieldCheck } from "lucide-react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { recordAuditEvent } from "@/lib/dis/audit";
import { canViewRawPii } from "@/lib/dis/permissions";
import { redact, shouldRedact } from "@/lib/dis/pii";
import type {
  CanonicalSchemaDomain,
  ColumnMapping,
} from "@/types/dis";

type Props = {
  uploadId: string;
  columns: ColumnMapping[];
  // Active mapping draft (or confirmed mapping). Used to look up
  // canonical_field_id per source column so PII tags from the schema
  // can drive redaction even before confirm.
  activeMappings: Record<string, string | null>;
  schema: CanonicalSchemaDomain[];
};

// Renders up to 5 sample rows derived from the per-column sample_values
// array (zip column[N]). Real backend will return row-coherent data;
// MSW approximates by zipping. The redaction layer treats each cell
// independently, so the approximation doesn't affect PII handling.
//
// View raw is per-row (Phase 5c.1c A2): one click reveals the row's
// raw values across all columns and emits a single audit event with
// the list of revealed columns. Hidden entirely when persona lacks
// dis.pii.view (canViewRawPii returns false). Reveal state is
// component-local; refresh re-redacts.

const MAX_ROWS = 5;

export function SampleRowsTable({ uploadId, columns, activeMappings, schema }: Props) {
  const snapshot = useAuthSnapshot();
  const canRevealRaw = canViewRawPii(snapshot?.user);
  const [revealed, setRevealed] = useState<Set<number>>(new Set());

  // Derive rows by zipping. rowCount is bounded by MAX_ROWS and the
  // shortest sample_values array (in practice all are length 5).
  const rowCount = Math.min(
    MAX_ROWS,
    columns.reduce(
      (min, c) => Math.min(min, c.sample_values.length),
      MAX_ROWS,
    ),
  );

  if (rowCount === 0 || columns.length === 0) return null;

  function toggleRow(rowIdx: number) {
    setRevealed((prev) => {
      const next = new Set(prev);
      if (next.has(rowIdx)) {
        next.delete(rowIdx);
      } else {
        next.add(rowIdx);
        const revealedColumns = columns
          .filter((c) => {
            const value = c.sample_values[rowIdx] ?? "";
            return shouldRedact(value, activeMappings[c.source_column], schema);
          })
          .map((c) => c.source_column);
        if (revealedColumns.length > 0) {
          recordAuditEvent({
            event_type: "pii_viewed",
            upload_id: uploadId,
            revealed_columns: revealedColumns,
          });
        }
      }
      return next;
    });
  }

  return (
    <div className="flex flex-col gap-2 px-6 py-4">
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-subheading">Sample data preview</h3>
        <span className="text-caption text-muted-foreground">
          ({rowCount} {rowCount === 1 ? "row" : "rows"}, redacted by default)
        </span>
      </div>
      <div className="overflow-x-auto rounded-md border border-border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-12 text-label text-muted-foreground">#</TableHead>
              {columns.map((c) => (
                <TableHead
                  key={c.source_column}
                  className="text-label text-muted-foreground font-mono"
                >
                  {c.source_column}
                </TableHead>
              ))}
              {canRevealRaw ? <TableHead className="w-28" /> : null}
            </TableRow>
          </TableHeader>
          <TableBody>
            {Array.from({ length: rowCount }).map((_, rowIdx) => {
              const isRevealed = revealed.has(rowIdx);
              return (
                <TableRow key={rowIdx}>
                  <TableCell className="text-caption text-muted-foreground tabular-nums">
                    {rowIdx + 1}
                  </TableCell>
                  {columns.map((c) => {
                    const raw = c.sample_values[rowIdx] ?? "";
                    const needsRedaction = shouldRedact(
                      raw,
                      activeMappings[c.source_column],
                      schema,
                    );
                    const display =
                      needsRedaction && !(canRevealRaw && isRevealed) ? redact(raw) : raw;
                    return (
                      <TableCell
                        key={c.source_column}
                        className="text-sm font-mono text-muted-foreground"
                      >
                        {display}
                      </TableCell>
                    );
                  })}
                  {canRevealRaw ? (
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => toggleRow(rowIdx)}
                        aria-pressed={isRevealed}
                      >
                        {isRevealed ? (
                          <>
                            <EyeOff className="h-4 w-4" />
                            Hide
                          </>
                        ) : (
                          <>
                            <Eye className="h-4 w-4" />
                            View raw
                          </>
                        )}
                      </Button>
                    </TableCell>
                  ) : null}
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
