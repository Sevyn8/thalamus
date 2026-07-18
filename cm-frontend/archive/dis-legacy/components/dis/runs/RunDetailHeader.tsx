"use client";

import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

import { RunStatusChip } from "@/components/dis/chips/RunStatusChip";
import { RunTriggeredByChip } from "@/components/dis/chips/RunTriggeredByChip";
import { SystemKindChip } from "@/components/dis/chips/SystemKindChip";
import type { Run } from "@/types/dis";

type Props = {
  run: Run;
};

export function RunDetailHeader({ run }: Props) {
  return (
    <div className="flex flex-col gap-4 rounded-md border border-border bg-card/30 p-6">
      <div className="flex items-center gap-3 flex-wrap">
        <RunStatusChip status={run.status} />
        <RunTriggeredByChip triggeredBy={run.triggered_by} />
        <SystemKindChip type={run.source_type} />
      </div>
      <div className="flex flex-col gap-1">
        <Link
          href={`/dis/streams/${run.stream_id}`}
          className="text-subheading text-primary hover:underline"
        >
          {run.source_name}
        </Link>
        <p className="text-caption text-muted-foreground">
          {run.tenant_name}
        </p>
      </div>
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field
          label="Started"
          value={
            run.started_at
              ? formatDistanceToNow(new Date(run.started_at), { addSuffix: true })
              : "—"
          }
        />
        <Field
          label="Finished"
          value={
            run.finished_at
              ? formatDistanceToNow(new Date(run.finished_at), { addSuffix: true })
              : run.status === "RUNNING"
                ? "In progress"
                : "—"
          }
        />
        <Field label="Duration" value={formatDuration(run.duration_ms)} />
        {run.triggered_by === "MANUAL" && run.triggered_by_user_name ? (
          <Field
            label="Triggered by"
            value={run.triggered_by_user_name}
            className="sm:col-span-3"
          />
        ) : null}
      </dl>
      {/* Phase 5c.4-polish cross-link (BUILD_PLAN deferred entry):
          lands on the source's detail page; the Alerts tab scopes to
          this source's alerts. Pattern matches FreshnessDetailView. */}
      <Link
        href={`/dis/streams/${run.stream_id}`}
        className="inline-flex w-fit items-center gap-1 text-sm text-primary hover:underline"
      >
        View related alerts
        <ExternalLink className="h-3 w-3" />
      </Link>
    </div>
  );
}

function Field({
  label,
  value,
  className,
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div className={className}>
      <dt className="text-label text-muted-foreground">{label}</dt>
      <dd className="text-sm">{value}</dd>
    </div>
  );
}

function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)}s`;
  const m = Math.floor(s / 60);
  const r = Math.round(s - m * 60);
  return r === 0 ? `${m}m` : `${m}m ${r}s`;
}
