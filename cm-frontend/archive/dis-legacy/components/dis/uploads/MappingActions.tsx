"use client";

import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";

type Props = {
  canConfirm: boolean;
  confirming: boolean;
  unmappedCount: number;
  onConfirm: () => void;
  onCancel: () => void;
};

// Mapping review actions. No progress indicator (per 5c.1b A9): the
// disabled state on Confirm + per-row state in the table is enough
// signal. A brief inline help line clarifies *why* Confirm is disabled
// when the user can't act.
export function MappingActions({
  canConfirm,
  confirming,
  unmappedCount,
  onConfirm,
  onCancel,
}: Props) {
  return (
    <div className="flex items-center justify-between gap-3 border-t border-border bg-card/30 px-6 py-4">
      <div className="text-caption text-muted-foreground">
        {canConfirm
          ? "Ready to confirm and start ingest."
          : `${unmappedCount} ${unmappedCount === 1 ? "column" : "columns"} still need a mapping or ignore decision.`}
      </div>
      <div className="flex items-center gap-2">
        <Button variant="ghost" onClick={onCancel} disabled={confirming}>
          Cancel
        </Button>
        <Button onClick={onConfirm} disabled={!canConfirm || confirming}>
          {confirming ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Confirming…
            </>
          ) : (
            "Confirm mapping"
          )}
        </Button>
      </div>
    </div>
  );
}
