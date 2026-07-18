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
import { AlertEventStateChip } from "@/components/dis/chips/AlertEventStateChip";
import { AlertSeverityChip } from "@/components/dis/chips/AlertSeverityChip";
import { useAlertEvents } from "@/lib/dis/hooks/use-alerts";
import type { AlertEvent, AlertEventListParams } from "@/types/dis";

// Phase 5c.4d-events: shared alerts events table for the per-source
// tab + the fleet view. context controls column set:
//   - "source": omits Source / Tenant cols (already scoped)
//   - "stream": Phase 5e.4b — same column treatment as "source".
//   - "fleet":  includes Source + Tenant cols

type Context = "source" | "stream" | "fleet";

type Props = {
  context: Context;
  sourceId?: string;
  streamId?: string;
  params?: AlertEventListParams;
  emptyState?: { title: string; body?: string };
};

export function AlertEventsTable({
  context,
  sourceId,
  streamId,
  params,
  emptyState,
}: Props) {
  const finalParams: AlertEventListParams = {
    ...(params ?? {}),
    ...(sourceId ? { source_id: sourceId } : {}),
    ...(streamId ? { stream_id: streamId } : {}),
    limit: params?.limit ?? 50,
  };
  const query = useAlertEvents(finalParams);

  if (query.isLoading) return <Skeleton variant="row" count={5} />;
  if (query.error) {
    return (
      <ErrorInline
        message="Could not load alert events."
        onRetry={() => query.refetch()}
      />
    );
  }
  const items = query.data?.items ?? [];
  if (items.length === 0) return <AlertsEmptyState context={context} override={emptyState} />;
  return <AlertsTableInner context={context} events={items} />;
}

function AlertsTableInner({
  context,
  events,
}: {
  context: Context;
  events: AlertEvent[];
}) {
  const router = useRouter();
  const showSourceCols = context === "fleet";
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="px-3 text-label text-muted-foreground">Severity</TableHead>
          <TableHead className="text-label text-muted-foreground">State</TableHead>
          <TableHead className="text-label text-muted-foreground">Trigger</TableHead>
          {showSourceCols ? (
            <>
              <TableHead className="text-label text-muted-foreground">Source</TableHead>
              <TableHead className="text-label text-muted-foreground">Tenant</TableHead>
            </>
          ) : null}
          <TableHead className="text-label text-muted-foreground">Channel</TableHead>
          <TableHead className="text-label text-muted-foreground">Acknowledged by</TableHead>
          <TableHead className="text-label text-muted-foreground">Fired</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {events.map((e) => (
          <TableRow
            key={e.id}
            onClick={() => router.push(`/dis/alerts/${e.id}`)}
            className="cursor-pointer"
          >
            <TableCell className="px-3 py-3">
              <AlertSeverityChip severity={e.severity} />
            </TableCell>
            <TableCell>
              <AlertEventStateChip state={e.state} />
            </TableCell>
            <TableCell>
              <div className="flex min-w-0 flex-col gap-1">
                <span className="font-mono text-xs text-muted-foreground">
                  {e.trigger_type}
                </span>
                <span className="truncate text-sm" title={e.trigger_description}>
                  {e.trigger_description}
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
              <div className="flex flex-col gap-0.5">
                <span className="font-mono text-xs text-muted-foreground">{e.channel}</span>
                <span className="truncate text-xs">{e.recipient}</span>
              </div>
            </TableCell>
            <TableCell>
              <span className="text-xs text-muted-foreground">
                {e.acknowledged_by_user_name ?? "—"}
              </span>
            </TableCell>
            <TableCell>
              <span className="text-xs text-muted-foreground">
                {formatDistanceToNow(new Date(e.fired_at), { addSuffix: true })}
              </span>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function AlertsEmptyState({
  context,
  override,
}: {
  context: Context;
  override?: { title: string; body?: string };
}) {
  const title =
    override?.title ??
    (context === "source"
      ? "No alert events for this source yet."
      : context === "stream"
        ? "No alert events for this stream yet."
        : "No alert events match these filters");
  const body =
    override?.body ??
    (context === "fleet" ? "Try widening the state filter." : undefined);
  return (
    <div className="flex flex-col items-center gap-3 rounded-md border border-dashed border-border px-6 py-10 text-center">
      <h3 className="text-sm font-medium">{title}</h3>
      {body ? <p className="text-caption text-muted-foreground">{body}</p> : null}
    </div>
  );
}
