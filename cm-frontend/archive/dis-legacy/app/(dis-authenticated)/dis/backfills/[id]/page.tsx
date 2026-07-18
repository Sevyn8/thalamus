"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { format, formatDistanceToNow } from "date-fns";

import { PageHeader } from "@/components/shared/PageHeader";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { BackfillStatusChip } from "@/components/dis/chips/BackfillStatusChip";
import { useBackfill } from "@/lib/dis/hooks/use-backfills";
import type { Backfill } from "@/types/dis";

// Phase 5c.6b: backfill detail. Header card with metadata + window
// + status + roll-up rows + spawned runs list cross-linking to
// /dis/runs/[run_id]. Read-only — cancel + retry-spawned-run defer
// to Phase 5d backend support.

export default function BackfillDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const query = useBackfill(id);

  if (query.isLoading) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Backfill" />
        <section className="px-6 py-6">
          <Skeleton variant="row" count={4} />
        </section>
      </div>
    );
  }

  if (query.error || !query.data) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Backfill" />
        <section className="flex flex-col gap-4 px-6 py-6">
          <ErrorInline message="Could not load backfill." onRetry={() => query.refetch()} />
          <BackLink />
        </section>
      </div>
    );
  }

  const backfill = query.data;

  return (
    <div className="flex flex-1 flex-col">
      <PageHeader
        title={`Backfill · ${backfill.source_name}`}
        subtitle={backfill.tenant_name}
      />
      <section className="flex flex-col gap-6 px-6 py-6">
        <BackLink />
        <Header backfill={backfill} />
        <SpawnedRuns backfill={backfill} />
      </section>
    </div>
  );
}

function BackLink() {
  return (
    <Link
      href="/dis/backfills"
      className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="h-3.5 w-3.5" />
      Back to backfills
    </Link>
  );
}

function Header({ backfill }: { backfill: Backfill }) {
  const showEta =
    backfill.status === "QUEUED" || backfill.status === "RUNNING";
  return (
    <div className="flex flex-col gap-4 rounded-md border border-border bg-card/30 p-6">
      <div className="flex flex-wrap items-center gap-2">
        <BackfillStatusChip status={backfill.status} />
        <span className="font-mono text-xs text-muted-foreground">{backfill.id}</span>
      </div>
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field
          label="Stream"
          value={
            <Link
              href={`/dis/streams/${backfill.stream_id}`}
              className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
            >
              {backfill.stream_name}
              <ExternalLink className="h-3 w-3" />
            </Link>
          }
        />
        <Field
          label="Window"
          value={
            <div className="flex flex-col gap-0.5">
              <span className="text-sm">
                {formatWindow(backfill.window_start, backfill.window_end)}
              </span>
              <span className="font-mono text-micro text-muted-foreground">
                {windowDays(backfill.window_start, backfill.window_end)} days
              </span>
            </div>
          }
        />
        <Field
          label="Requested by"
          value={
            <div className="flex flex-col gap-0.5">
              <span className="text-sm">{backfill.requested_by_user_name}</span>
              <span className="text-micro text-muted-foreground">
                {formatDistanceToNow(new Date(backfill.requested_at), { addSuffix: true })}
              </span>
            </div>
          }
        />
        <Field
          label="Rows ingested"
          value={
            <span className="text-sm font-medium">
              {backfill.rows_ingested.toLocaleString()}
            </span>
          }
        />
        <Field
          label="Rows failed"
          value={
            <span
              className={
                backfill.rows_failed > 0
                  ? "text-sm font-medium text-danger"
                  : "text-sm text-muted-foreground"
              }
            >
              {backfill.rows_failed.toLocaleString()}
            </span>
          }
        />
        {showEta ? (
          <Field
            label="Estimated completion"
            value={
              <span className="text-sm text-muted-foreground">
                {backfill.estimated_completion_at
                  ? formatDistanceToNow(new Date(backfill.estimated_completion_at), {
                      addSuffix: true,
                    })
                  : "—"}
              </span>
            }
          />
        ) : (
          <Field
            label="Completed"
            value={
              <span className="text-sm text-muted-foreground">
                {backfill.completed_at
                  ? formatDistanceToNow(new Date(backfill.completed_at), {
                      addSuffix: true,
                    })
                  : "—"}
              </span>
            }
          />
        )}
      </dl>
      {backfill.error_summary ? (
        <div className="flex flex-col gap-1 rounded-md border border-danger/40 bg-danger/5 p-3">
          <span className="text-label text-danger">Error summary</span>
          <p className="text-sm">{backfill.error_summary}</p>
        </div>
      ) : null}
    </div>
  );
}

function SpawnedRuns({ backfill }: { backfill: Backfill }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-heading">Spawned runs</h2>
        <span className="text-caption text-muted-foreground">
          {backfill.spawned_run_ids.length}
        </span>
      </div>
      {backfill.spawned_run_ids.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border px-6 py-10 text-center">
          <p className="text-sm font-medium">No runs spawned yet</p>
          <p className="text-caption text-muted-foreground">
            {backfill.status === "QUEUED"
              ? "Runs will spawn when the backfill begins executing."
              : "This backfill did not produce any runs."}
          </p>
        </div>
      ) : (
        <ul className="flex flex-col rounded-md border border-border bg-card/20">
          {backfill.spawned_run_ids.map((runId) => (
            <li
              key={runId}
              className="flex items-center justify-between gap-3 border-b border-border px-4 py-3 last:border-b-0"
            >
              <span className="font-mono text-xs text-muted-foreground">{runId}</span>
              <Link
                href={`/dis/runs/${runId}`}
                className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
              >
                Open run
                <ExternalLink className="h-3 w-3" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-label text-muted-foreground">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

// Same window formatting as BackfillsTable. Could be extracted to
// a shared util if a third consumer surfaces; two consumers don't
// merit lift yet.
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
