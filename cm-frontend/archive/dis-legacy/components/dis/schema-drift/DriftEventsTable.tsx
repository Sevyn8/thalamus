"use client";

import { useRouter } from "next/navigation";
import { formatDistanceToNow } from "date-fns";

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
import { DriftSeverityChip } from "@/components/dis/chips/DriftSeverityChip";
import { useDriftEvents } from "@/lib/dis/hooks/use-schema-drift";
import type { DriftEvent, DriftListParams } from "@/types/dis";

import { formatDriftDiff } from "./formatDriftDiff";

// Phase 5c.4b: shared drift-events table for the per-source tab + the
// fleet view. context controls column set:
//   - "source": omits Source / Tenant cols (already scoped)
//   - "stream": Phase 5e.4b — same column treatment as "source".
//   - "fleet":  includes Source + Tenant cols

type Context = "source" | "stream" | "fleet";

type Props = {
  context: Context;
  sourceId?: string;
  streamId?: string;
  params?: DriftListParams;
  emptyState?: { title: string; body?: string };
};

export function DriftEventsTable({
  context,
  sourceId,
  streamId,
  params,
  emptyState,
}: Props) {
  const finalParams: DriftListParams = {
    ...(params ?? {}),
    ...(sourceId ? { source_id: sourceId } : {}),
    ...(streamId ? { stream_id: streamId } : {}),
    limit: params?.limit ?? 50,
  };
  const query = useDriftEvents(finalParams);

  if (query.isLoading) return <Skeleton variant="row" count={5} />;
  if (query.error) {
    return (
      <ErrorInline
        message="Could not load drift events."
        onRetry={() => query.refetch()}
      />
    );
  }
  const items = query.data?.items ?? [];
  if (items.length === 0) return <DriftEmptyState context={context} override={emptyState} />;
  return <DriftTableInner context={context} events={items} />;
}

function DriftTableInner({ context, events }: { context: Context; events: DriftEvent[] }) {
  const router = useRouter();
  const showSourceCols = context === "fleet";
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="px-3 text-label text-muted-foreground">Severity</TableHead>
          <TableHead className="text-label text-muted-foreground">Event</TableHead>
          {showSourceCols ? (
            <>
              <TableHead className="text-label text-muted-foreground">Source</TableHead>
              <TableHead className="text-label text-muted-foreground">Tenant</TableHead>
            </>
          ) : null}
          <TableHead className="text-label text-muted-foreground">Diff</TableHead>
          <TableHead className="text-label text-muted-foreground">Detected</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {events.map((e) => (
          <TableRow
            key={e.id}
            onClick={() => router.push(`/dis/validation/drift/${e.id}`)}
            className="cursor-pointer"
          >
            <TableCell className="px-3 py-3">
              <DriftSeverityChip severity={e.severity} />
            </TableCell>
            <TableCell>
              <div className="flex min-w-0 flex-col gap-1">
                <span className="font-mono text-xs text-muted-foreground">
                  {e.event_type}
                </span>
                <span className="truncate text-sm font-medium" title={e.column_name}>
                  {e.column_name}
                </span>
              </div>
            </TableCell>
            {showSourceCols ? (
              <>
                <TableCell>
                  <span className="truncate text-sm">{e.source_name}</span>
                </TableCell>
                <TableCell>
                  <span className="text-sm">{e.tenant_name}</span>
                </TableCell>
              </>
            ) : null}
            <TableCell>
              <span className="font-mono text-xs">{formatDriftDiff(e)}</span>
            </TableCell>
            <TableCell>
              <span className="text-xs text-muted-foreground">
                {formatDistanceToNow(new Date(e.detected_at), { addSuffix: true })}
              </span>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function DriftEmptyState({
  context,
  override,
}: {
  context: Context;
  override?: { title: string; body?: string };
}) {
  const title =
    override?.title ??
    (context === "source"
      ? "No drift events for this source yet."
      : context === "stream"
        ? "No drift events for this stream yet."
        : "No drift events match these filters");
  const body =
    override?.body ??
    (context === "fleet" ? "Try widening the severity filter." : undefined);
  return (
    <div className="flex flex-col items-center gap-3 rounded-md border border-dashed border-border px-6 py-10 text-center">
      <h3 className="text-sm font-medium">{title}</h3>
      {body ? <p className="text-caption text-muted-foreground">{body}</p> : null}
    </div>
  );
}
