"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import { useRunNow } from "@/lib/dis/hooks/use-sources";
import type { Run } from "@/types/dis";

// Phase 5c.3b: error panel for FAILED runs. Two affordances per A iv:
//
//   Primary: "Run now on source" — wraps the existing useRunNow
//            mutation (5c.3a). Same effect as the lifecycle Run now,
//            but in-context for the user investigating a failure.
//            Toast + cache invalidation on success; the new
//            SUCCEEDED run shows up at the top of the source's Runs
//            tab and in this fleet view's data on next refetch.
//
//   Secondary: "Open source" link — for users who want to look at
//              the source itself (config, schedule) before retrying.
//
// Deliberately NOT framed as "retry this run" — that would imply
// per-run retry semantics (re-attempt with same window? backfill
// that period?) which aren't a v1 contract concern. Re-running the
// source is the v1 action.

type Props = {
  run: Run;
};

export function RunErrorPanel({ run }: Props) {
  const runNow = useRunNow(run.source_id);
  const [actionError, setActionError] = useState<string | null>(null);

  async function onRunNow() {
    setActionError(null);
    try {
      const created = await runNow.mutateAsync();
      toast.success(
        `Run completed — ${(created.rows_ingested ?? 0).toLocaleString()} rows`,
      );
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Run now failed.");
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-md border border-danger/40 bg-danger/5 p-5 dark:border-red-500/40 dark:bg-red-500/5">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden="true" />
        <div className="flex flex-col gap-1">
          <h3 className="text-subheading text-danger">Run failed</h3>
          {run.error_code ? (
            <p className="text-caption font-mono text-muted-foreground">
              {run.error_code}
            </p>
          ) : null}
          {run.error_message ? (
            <p className="text-sm">{run.error_message}</p>
          ) : null}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={onRunNow} disabled={runNow.isPending}>
          {runNow.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
          Run now on source
        </Button>
        <Link
          href={`/dis/streams/${run.stream_id}`}
          className="text-sm text-primary hover:underline"
        >
          Open stream →
        </Link>
      </div>
      {actionError ? (
        <p className="text-caption text-danger" role="alert">
          {actionError}
        </p>
      ) : null}
    </div>
  );
}
