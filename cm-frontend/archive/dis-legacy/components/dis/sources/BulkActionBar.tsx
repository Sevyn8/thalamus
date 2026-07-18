"use client";

import { useState } from "react";
import { Loader2, Pause, Play, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import {
  useBulkDelete,
  useBulkPause,
  useBulkResume,
} from "@/lib/dis/hooks/use-sources";
import type { BulkActionResultItem } from "@/types/dis";

// Phase 5c.2c2: sticky-bottom action bar that appears when selection > 0.
// Fixed-bottom positioning accounts for the sidebar offset via the
// ml-60 (matching Sidebar.tsx's expanded width). Disappears at 0
// selected. Per A11: full-success → toast; mixed → toast description
// with skipped breakdown.

const SIDEBAR_OFFSET_CLASS = "left-60"; // matches Sidebar's w-60

type Props = {
  selection: Set<string>;
  selectedSourceLabels: Map<string, string>; // source_id → name (for skip-result display)
  onClearSelection: () => void;
};

export function BulkActionBar({
  selection,
  selectedSourceLabels,
  onClearSelection,
}: Props) {
  const bulkPause = useBulkPause();
  const bulkResume = useBulkResume();
  const bulkDelete = useBulkDelete();
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  if (selection.size === 0) return null;

  function summarize(results: BulkActionResultItem[], action: string) {
    const successes = results.filter((r) => r.success).length;
    const failures = results.filter((r) => !r.success);
    if (failures.length === 0) {
      toast.success(`${action}: ${successes} succeeded`);
      return;
    }
    const skipLines = failures
      .slice(0, 3)
      .map((f) => {
        const name = selectedSourceLabels.get(f.source_id) ?? f.source_id;
        return `• ${name} — ${f.error_code ?? "skipped"}`;
      })
      .join("\n");
    const more = failures.length > 3 ? `\n• …and ${failures.length - 3} more` : "";
    toast(`${action}: ${successes} of ${results.length} succeeded`, {
      description: `${skipLines}${more}`,
    });
  }

  async function runPause() {
    try {
      const res = await bulkPause.mutateAsync(Array.from(selection));
      summarize(res.results, "Pause");
      onClearSelection();
    } catch {
      toast.error("Bulk pause failed.");
    }
  }
  async function runResume() {
    try {
      const res = await bulkResume.mutateAsync(Array.from(selection));
      summarize(res.results, "Resume");
      onClearSelection();
    } catch {
      toast.error("Bulk resume failed.");
    }
  }
  async function runDelete() {
    try {
      const res = await bulkDelete.mutateAsync(Array.from(selection));
      summarize(res.results, "Delete");
      onClearSelection();
    } catch {
      toast.error("Bulk delete failed.");
    }
  }

  const anyPending =
    bulkPause.isPending || bulkResume.isPending || bulkDelete.isPending;

  return (
    <>
      <div
        className={`fixed bottom-0 right-0 z-30 flex items-center justify-between gap-3 border-t border-border bg-background px-6 py-3 shadow-md ${SIDEBAR_OFFSET_CLASS}`}
        role="region"
        aria-label="Bulk actions"
      >
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="sm"
            onClick={onClearSelection}
            disabled={anyPending}
            aria-label="Clear selection"
          >
            <X className="h-4 w-4" />
          </Button>
          <span className="text-sm font-medium">{selection.size} selected</span>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={runPause} disabled={anyPending}>
            {bulkPause.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Pause className="h-4 w-4" />}
            Pause
          </Button>
          <Button variant="outline" size="sm" onClick={runResume} disabled={anyPending}>
            {bulkResume.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            Resume
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setConfirmDeleteOpen(true)}
            disabled={anyPending}
            className="text-danger hover:text-danger"
          >
            <Trash2 className="h-4 w-4" />
            Delete
          </Button>
        </div>
      </div>

      <ConfirmDialog
        open={confirmDeleteOpen}
        onOpenChange={setConfirmDeleteOpen}
        title={`Delete ${selection.size} source${selection.size === 1 ? "" : "s"}?`}
        body="This permanently removes the selected sources and stops their ingest. Active runs are not affected; historical run records remain."
        confirmLabel={`Delete ${selection.size}`}
        variant="destructive"
        onConfirm={runDelete}
      />
    </>
  );
}
