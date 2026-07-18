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
import { FreshnessStateChip } from "@/components/dis/chips/FreshnessStateChip";
import { useFreshnessList } from "@/lib/dis/hooks/use-freshness";
import type { Freshness, FreshnessListParams } from "@/types/dis";

// Phase 5c.4c: fleet-only table (one row per source, current SLO
// state). Per-source view uses FreshnessDetailView directly rather
// than this table — freshness is 1:1 with source so a per-source
// table would render exactly one row.

type Props = {
  params?: FreshnessListParams;
};

export function FreshnessTable({ params }: Props) {
  const finalParams: FreshnessListParams = {
    ...(params ?? {}),
    limit: params?.limit ?? 50,
  };
  const query = useFreshnessList(finalParams);

  if (query.isLoading) return <Skeleton variant="row" count={5} />;
  if (query.error) {
    return (
      <ErrorInline
        message="Could not load freshness records."
        onRetry={() => query.refetch()}
      />
    );
  }
  const items = query.data?.items ?? [];
  if (items.length === 0) return <FreshnessEmptyState />;
  return <FreshnessTableInner records={items} />;
}

function FreshnessTableInner({ records }: { records: Freshness[] }) {
  const router = useRouter();
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="px-3 text-label text-muted-foreground">State</TableHead>
          <TableHead className="text-label text-muted-foreground">Stream</TableHead>
          <TableHead className="text-label text-muted-foreground">Tenant</TableHead>
          <TableHead className="text-label text-muted-foreground">Expected</TableHead>
          <TableHead className="text-label text-muted-foreground">Last data</TableHead>
          <TableHead className="text-label text-muted-foreground">Delay</TableHead>
          <TableHead className="text-label text-muted-foreground text-right">
            Breaches (30d)
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {records.map((r) => (
          <TableRow
            key={r.id}
            onClick={() => router.push(`/dis/freshness/${r.id}`)}
            className="cursor-pointer"
          >
            <TableCell className="px-3 py-3">
              <FreshnessStateChip state={r.current_state} />
            </TableCell>
            <TableCell>
              <span className="truncate text-sm font-medium">{r.stream_name}</span>
            </TableCell>
            <TableCell>
              <span className="text-sm">{r.tenant_name}</span>
            </TableCell>
            <TableCell>
              <span className="text-sm">{r.expected_frequency}</span>
            </TableCell>
            <TableCell>
              <span className="text-xs text-muted-foreground">
                {r.last_data_received_at
                  ? formatDistanceToNow(new Date(r.last_data_received_at), {
                      addSuffix: true,
                    })
                  : "—"}
              </span>
            </TableCell>
            <TableCell>
              <span
                className={
                  r.delay_seconds > 0
                    ? "text-sm font-medium text-danger"
                    : "text-sm text-muted-foreground"
                }
              >
                {r.delay_seconds > 0 ? formatDuration(r.delay_seconds * 1000) : "—"}
              </span>
            </TableCell>
            <TableCell className="text-right">
              <span
                className={
                  r.breach_count_30d > 0
                    ? "text-sm font-medium text-danger"
                    : "text-sm text-muted-foreground"
                }
              >
                {r.breach_count_30d}
              </span>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

// Inline duration formatter. Same shape as the helper in
// RunsTable/RunDetailHeader; second consumer doesn't justify a shared
// extraction yet (see ix in 5c.4c plan).
function formatDuration(ms: number): string {
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`;
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)}m`;
  if (ms < 86_400_000) return `${Math.round(ms / 3_600_000)}h`;
  return `${Math.round(ms / 86_400_000)}d`;
}

function FreshnessEmptyState() {
  return (
    <div className="flex flex-col items-center gap-3 rounded-md border border-dashed border-border px-6 py-10 text-center">
      <h3 className="text-sm font-medium">No freshness records match these filters</h3>
      <p className="text-caption text-muted-foreground">
        Try widening the state filter.
      </p>
    </div>
  );
}
