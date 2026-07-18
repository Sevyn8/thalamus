"use client";

import { useRouter } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import { ArrowUp, Loader2 } from "lucide-react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { Skeleton } from "@/components/shared/Skeleton";
import { RunStatusChip } from "@/components/dis/chips/RunStatusChip";
import { RunTriggeredByChip } from "@/components/dis/chips/RunTriggeredByChip";
import { SystemKindChip } from "@/components/dis/chips/SystemKindChip";
import { useRuns } from "@/lib/dis/hooks/use-runs";
import { cn } from "@/lib/utils";
import type { Run, RunListParams } from "@/types/dis";

// Phase 5c.3a: shared runs table for the per-source Runs tab and the
// (5c.3b) cross-tenant fleet view. `context` controls column set:
//   - "source": source-detail tab; omits Source + Tenant columns since
//     the row is already scoped to the surrounding source.
//   - "stream": Phase 5e.4b — Stream detail page tab. Same column
//     treatment as "source" since runs are now per-feed. Caller passes
//     streamId; table filters via stream_id query param.
//   - "fleet":  /dis/runs page; includes Source + Tenant columns.
//
// Row click navigates to /dis/runs/[id]; the detail page lands in
// 5c.3b. Until then the route is a no-op stub (Next.js renders a
// minimal placeholder via app/(dis-authenticated)/dis/runs/[id]/page.tsx
// once that file exists). For 5c.3a, click is wired but the
// destination is documented as not-yet-implemented.

type Context = "source" | "stream" | "fleet";

type Props = {
  context: Context;
  // For source-tab usage. Caller passes sourceId; table fetches that
  // source's runs. For fleet usage (5c.3b), pass `params` directly
  // with whatever filters apply.
  sourceId?: string;
  streamId?: string;
  params?: RunListParams;
  // When provided, replaces the default empty-state copy. The source-
  // tab consumer uses this to show the "Click 'Run now' above" hint
  // (per 5c.3a #16 refinement); fleet leaves the default.
  emptyState?: { title: string; body?: string };
  // Phase 5c.3b: when the fleet page owns pagination via
  // useInfiniteRuns, it passes already-loaded items here so the table
  // doesn't double-fetch. Source-tab usage leaves this undefined and
  // the table fetches its own data via useRuns.
  preloaded?: Run[];
};

export function RunsTable({
  context,
  sourceId,
  streamId,
  params,
  emptyState,
  preloaded,
}: Props) {
  const usePreloaded = preloaded !== undefined;
  const finalParams: RunListParams = {
    ...(params ?? {}),
    ...(sourceId ? { source_id: sourceId } : {}),
    ...(streamId ? { stream_id: streamId } : {}),
    limit: params?.limit ?? 25,
  };
  // Skip the internal fetch entirely when caller provided preloaded.
  const query = useRuns(finalParams, { enabled: !usePreloaded });

  if (!usePreloaded && query.isLoading) {
    return <Skeleton variant="row" count={5} />;
  }
  if (!usePreloaded && query.error) {
    return (
      <ErrorInline
        message="Could not load runs."
        onRetry={() => query.refetch()}
      />
    );
  }

  const items = usePreloaded ? preloaded! : (query.data?.items ?? []);
  if (items.length === 0) {
    return <RunsEmptyState context={context} override={emptyState} />;
  }

  return <RunsTableInner context={context} runs={items} />;
}

function RunsTableInner({
  context,
  runs,
}: {
  context: Context;
  runs: Run[];
}) {
  const router = useRouter();
  const showSourceCols = context === "fleet";

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="px-3 text-label text-muted-foreground">Status</TableHead>
          {showSourceCols ? (
            <>
              <TableHead className="text-label text-muted-foreground">Source</TableHead>
              <TableHead className="text-label text-muted-foreground">Tenant</TableHead>
            </>
          ) : null}
          <TableHead className="text-label text-muted-foreground">Started</TableHead>
          <TableHead className="text-label text-muted-foreground">Duration</TableHead>
          <TableHead className="text-label text-muted-foreground text-right">Rows</TableHead>
          <TableHead className="text-label text-muted-foreground">Trigger</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((r) => (
          <TableRow
            key={r.id}
            onClick={() => router.push(`/dis/runs/${r.id}`)}
            className="cursor-pointer"
          >
            <TableCell className="px-3 py-3">
              <RunStatusChip status={r.status} />
            </TableCell>
            {showSourceCols ? (
              <>
                <TableCell>
                  <div className="flex min-w-0 flex-col gap-1">
                    <span className="truncate text-sm font-medium">{r.source_name}</span>
                    <SystemKindChip type={r.source_type} />
                  </div>
                </TableCell>
                <TableCell>
                  <span className="text-sm">{r.tenant_name}</span>
                </TableCell>
              </>
            ) : null}
            <TableCell>
              <StartedCell run={r} />
            </TableCell>
            <TableCell>
              <DurationCell run={r} />
            </TableCell>
            <TableCell className="text-right">
              <RowsCell run={r} />
            </TableCell>
            <TableCell>
              <RunTriggeredByChip triggeredBy={r.triggered_by} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function StartedCell({ run }: { run: Run }) {
  if (run.status === "QUEUED" || !run.started_at) {
    return (
      <span className="text-xs text-muted-foreground italic">
        Awaiting start
      </span>
    );
  }
  return (
    <span className="text-xs text-muted-foreground">
      {formatDistanceToNow(new Date(run.started_at), { addSuffix: true })}
    </span>
  );
}

function DurationCell({ run }: { run: Run }) {
  if (run.status === "RUNNING") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" />
        Running
      </span>
    );
  }
  if (run.duration_ms === null) return <span className="text-xs text-muted-foreground">—</span>;
  return <span className="text-xs">{formatDuration(run.duration_ms)}</span>;
}

function RowsCell({ run }: { run: Run }) {
  if (run.rows_ingested === null) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <div className="flex flex-col items-end gap-0.5">
      <span className={cn("text-sm font-medium", run.rows_ingested === 0 && "text-muted-foreground")}>
        {run.rows_ingested.toLocaleString()}
      </span>
      {(run.rows_failed ?? 0) > 0 ? (
        <span className="text-micro text-danger">{run.rows_failed} failed</span>
      ) : null}
    </div>
  );
}

// Format milliseconds → human duration. Sub-minute uses seconds with
// one decimal; minute+ rolls up to "Xm Ys". Matches Linear / Stripe
// dashboard conventions.
function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  const minutes = Math.floor(seconds / 60);
  const remSeconds = Math.round(seconds - minutes * 60);
  return remSeconds === 0 ? `${minutes}m` : `${minutes}m ${remSeconds}s`;
}

// Empty-state overrides per #16 refinement: per-source tab points up
// to the lifecycle-row Run now button instead of suggesting a route
// or duplicating the affordance. Fleet view (5c.3b) just shows the
// neutral "no runs match" copy.
function RunsEmptyState({
  context,
  override,
}: {
  context: Context;
  override?: { title: string; body?: string };
}) {
  if (override) {
    return <EmptyShell title={override.title} body={override.body} />;
  }
  if (context === "source" || context === "stream") {
    return (
      <EmptyShell
        title="No runs yet"
        body={
          context === "source"
            ? "Click 'Run now' in the actions above to start the first ingest."
            : "No runs yet for this stream."
        }
        showArrow={context === "source"}
      />
    );
  }
  return (
    <EmptyShell
      title="No runs match these filters"
      body="Try widening the date range or clearing the status filter."
    />
  );
}

function EmptyShell({
  title,
  body,
  showArrow,
}: {
  title: string;
  body?: string;
  showArrow?: boolean;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-md border border-dashed border-border px-6 py-10 text-center">
      {showArrow ? (
        <ArrowUp className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
      ) : null}
      <h3 className="text-sm font-medium">{title}</h3>
      {body ? <p className="text-caption text-muted-foreground">{body}</p> : null}
    </div>
  );
}
