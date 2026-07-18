"use client";

import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

import { ErrorInline } from "@/components/shared/ErrorInline";
import { Skeleton } from "@/components/shared/Skeleton";
import { FreshnessStateChip } from "@/components/dis/chips/FreshnessStateChip";
import {
  useFreshnessForSource,
  useFreshnessForStream,
} from "@/lib/dis/hooks/use-freshness";
import type { FreshnessHistoryEvent } from "@/types/dis";

// Phase 5c.4c: shared between /dis/freshness/[id] detail page and the
// per-source Freshness tab on /dis/sources/[id]. The page wraps this
// in chrome (header + back link); the tab renders it bare. Same
// content, two consumption surfaces.
//
// Phase 5e.4b: accepts either sourceId OR streamId. Stream detail
// page (/dis/streams/[id]) passes streamId so multi-SLO sources (e.g.,
// Shopify orders + inventory) resolve to the correct per-feed SLO
// rather than the first record matching the parent source. The
// existing source-detail consumer continues to pass sourceId.

type Props =
  | { sourceId: string; streamId?: undefined }
  | { streamId: string; sourceId?: undefined };

export function FreshnessDetailView(props: Props) {
  const sourceQuery = useFreshnessForSource(props.sourceId ?? "");
  const streamQuery = useFreshnessForStream(props.streamId ?? "");
  const query = props.streamId ? streamQuery : sourceQuery;

  if (query.isLoading) return <Skeleton variant="row" count={4} />;
  if (query.error || !query.data) {
    return (
      <ErrorInline
        message="Could not load freshness."
        onRetry={() => query.refetch()}
      />
    );
  }
  const r = query.data;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-4 rounded-md border border-border bg-card/30 p-6">
        <div className="flex flex-wrap items-center gap-2">
          <FreshnessStateChip state={r.current_state} />
          <span className="text-sm text-muted-foreground">{r.expected_frequency}</span>
        </div>
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field
            label="Last data received"
            value={
              r.last_data_received_at
                ? formatDistanceToNow(new Date(r.last_data_received_at), {
                    addSuffix: true,
                  })
                : "—"
            }
          />
          <Field
            label="Delay"
            value={r.delay_seconds > 0 ? formatDuration(r.delay_seconds * 1000) : "—"}
            danger={r.delay_seconds > 0}
          />
          <Field
            label="Breaches (30d)"
            value={String(r.breach_count_30d)}
            danger={r.breach_count_30d > 0}
          />
        </dl>
        {/* Phase 5c.4d-events cross-link (deferred from 5c.4c xiii):
            tenant lands on the source's detail page; the Alerts tab
            scopes to this source's alerts. URL-param wiring on
            /dis/alerts deferred — landing on source-detail keeps
            consumer-side scope and gives the user all 6 lenses. */}
        <Link
          href={`/dis/streams/${r.stream_id}`}
          className="inline-flex w-fit items-center gap-1 text-sm text-primary hover:underline"
        >
          View related alerts
          <ExternalLink className="h-3 w-3" />
        </Link>
      </div>

      <HistorySection history={r.recent_history} />
    </div>
  );
}

function Field({
  label,
  value,
  danger,
}: {
  label: string;
  value: string;
  danger?: boolean;
}) {
  return (
    <div>
      <dt className="text-label text-muted-foreground">{label}</dt>
      <dd
        className={
          danger ? "text-sm font-medium text-danger" : "text-sm text-foreground"
        }
      >
        {value}
      </dd>
    </div>
  );
}

function HistorySection({ history }: { history: FreshnessHistoryEvent[] }) {
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-heading">Recent state changes</h2>
      {history.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border px-6 py-10 text-center">
          <p className="text-sm font-medium">No state changes recorded</p>
          <p className="text-caption text-muted-foreground">
            This SLO has held steady over the recent 30-day window.
          </p>
        </div>
      ) : (
        <ul className="flex flex-col rounded-md border border-border bg-card/20">
          {history.map((h, i) => (
            <li
              key={i}
              className="flex items-center justify-between gap-3 border-b border-border px-4 py-3 last:border-b-0"
            >
              <div className="flex items-center gap-3">
                {h.previous_state ? (
                  <FreshnessStateChip state={h.previous_state} />
                ) : (
                  <span className="text-xs text-muted-foreground">(initial)</span>
                )}
                <span className="text-muted-foreground">→</span>
                <FreshnessStateChip state={h.new_state} />
              </div>
              <span className="text-xs text-muted-foreground">
                {formatDistanceToNow(new Date(h.occurred_at), { addSuffix: true })}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function formatDuration(ms: number): string {
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`;
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)}m`;
  if (ms < 86_400_000) return `${Math.round(ms / 3_600_000)}h`;
  return `${Math.round(ms / 86_400_000)}d`;
}
