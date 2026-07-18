"use client";

import { useRouter } from "next/navigation";
import { format, formatDistanceToNow } from "date-fns";

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
import { BackfillStatusChip } from "@/components/dis/chips/BackfillStatusChip";
import { useBackfills } from "@/lib/dis/hooks/use-backfills";
import type { Backfill, BackfillListParams } from "@/types/dis";

// Phase 5c.6a → 5c.6b: backfills fleet table. Row click pushes to
// /dis/backfills/[id] (added in 5c.6b). context kept as a future-
// proofing slot consistent with AlertRulesTable / TemplatesTable;
// v1 only renders "fleet" content.

type Context = "fleet";

type Props = {
  context: Context;
  params?: BackfillListParams;
  emptyState?: { title: string; body?: string };
};

export function BackfillsTable({ context, params, emptyState }: Props) {
  const finalParams: BackfillListParams = {
    ...(params ?? {}),
    limit: params?.limit ?? 50,
  };
  const query = useBackfills(finalParams);

  if (query.isLoading) return <Skeleton variant="row" count={5} />;
  if (query.error) {
    return (
      <ErrorInline
        message="Could not load backfills."
        onRetry={() => query.refetch()}
      />
    );
  }
  const items = query.data?.items ?? [];
  if (items.length === 0) {
    return <BackfillsEmptyState context={context} override={emptyState} />;
  }
  return <BackfillsTableInner backfills={items} />;
}

function BackfillsTableInner({ backfills }: { backfills: Backfill[] }) {
  const router = useRouter();
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="px-3 text-label text-muted-foreground">Status</TableHead>
          <TableHead className="text-label text-muted-foreground">Source</TableHead>
          <TableHead className="text-label text-muted-foreground">Tenant</TableHead>
          <TableHead className="text-label text-muted-foreground">Window</TableHead>
          <TableHead className="text-label text-muted-foreground text-right">Rows</TableHead>
          <TableHead className="text-label text-muted-foreground">Requested by</TableHead>
          <TableHead className="text-label text-muted-foreground">Requested</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {backfills.map((b) => (
          <TableRow
            key={b.id}
            onClick={() => router.push(`/dis/backfills/${b.id}`)}
            className="cursor-pointer"
          >
            <TableCell className="px-3 py-3">
              <BackfillStatusChip status={b.status} />
            </TableCell>
            <TableCell>
              <span className="truncate text-sm" title={b.source_name}>
                {b.source_name}
              </span>
            </TableCell>
            <TableCell>
              <span className="text-sm">{b.tenant_name}</span>
            </TableCell>
            <TableCell>
              <div className="flex flex-col gap-0.5">
                <span className="text-sm">{formatWindow(b.window_start, b.window_end)}</span>
                <span className="font-mono text-micro text-muted-foreground">
                  {windowDays(b.window_start, b.window_end)}d
                </span>
              </div>
            </TableCell>
            <TableCell className="text-right">
              <div className="flex flex-col items-end gap-0.5">
                <span className="text-sm font-medium">
                  {b.rows_ingested.toLocaleString()}
                </span>
                {b.rows_failed > 0 ? (
                  <span className="text-micro text-danger">
                    {b.rows_failed.toLocaleString()} failed
                  </span>
                ) : null}
              </div>
            </TableCell>
            <TableCell>
              <span className="text-sm">{b.requested_by_user_name}</span>
            </TableCell>
            <TableCell>
              <span className="text-xs text-muted-foreground">
                {formatDistanceToNow(new Date(b.requested_at), { addSuffix: true })}
              </span>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function BackfillsEmptyState({
  context,
  override,
}: {
  context: Context;
  override?: { title: string; body?: string };
}) {
  void context;
  const title = override?.title ?? "No backfills match these filters";
  const body = override?.body ?? "Try widening the status filter.";
  return (
    <div className="flex flex-col items-center gap-3 rounded-md border border-dashed border-border px-6 py-10 text-center">
      <h3 className="text-sm font-medium">{title}</h3>
      <p className="text-caption text-muted-foreground">{body}</p>
    </div>
  );
}

// "May 1 – May 4, 2026" — same year on both sides drops the year on
// the start date. Cross-year windows render the year on both.
function formatWindow(startIso: string, endIso: string): string {
  const start = new Date(startIso);
  const end = new Date(endIso);
  if (start.getUTCFullYear() === end.getUTCFullYear()) {
    return `${format(start, "MMM d")} – ${format(end, "MMM d, yyyy")}`;
  }
  return `${format(start, "MMM d, yyyy")} – ${format(end, "MMM d, yyyy")}`;
}

function windowDays(startIso: string, endIso: string): number {
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  return Math.max(1, Math.round(ms / (1000 * 60 * 60 * 24)));
}
