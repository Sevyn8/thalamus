"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

import { PageHeader } from "@/components/shared/PageHeader";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { DriftSeverityChip } from "@/components/dis/chips/DriftSeverityChip";
import { formatDriftDiff } from "@/components/dis/schema-drift/formatDriftDiff";
import { useDriftEvent } from "@/lib/dis/hooks/use-schema-drift";
import type { DriftEvent } from "@/types/dis";

// Phase 5c.4b: drift event detail. Header card with event metadata +
// inline before/after diff + description + "Open run" CTA. No retry/
// acknowledge action — drift events are post-facto observations;
// state-transition workflows defer to Phase 5d backend support.

export default function DriftEventDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const query = useDriftEvent(id);

  if (query.isLoading) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Schema drift event" />
        <section className="px-6 py-6">
          <Skeleton variant="row" count={4} />
        </section>
      </div>
    );
  }

  if (query.error || !query.data) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Schema drift event" />
        <section className="flex flex-col gap-4 px-6 py-6">
          <ErrorInline
            message="Could not load drift event."
            onRetry={() => query.refetch()}
          />
          <Link
            href="/dis/validation/drift"
            className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to schema drift
          </Link>
        </section>
      </div>
    );
  }

  const event = query.data;
  return (
    <div className="flex flex-1 flex-col">
      <PageHeader
        title={`${event.event_type}: ${event.column_name}`}
        subtitle={event.source_name}
      />
      <section className="flex flex-col gap-6 px-6 py-6">
        <Link
          href="/dis/validation/drift"
          className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to schema drift
        </Link>
        <DriftHeader event={event} />
      </section>
    </div>
  );
}

function DriftHeader({ event }: { event: DriftEvent }) {
  return (
    <div className="flex flex-col gap-4 rounded-md border border-border bg-card/30 p-6">
      <div className="flex flex-wrap items-center gap-2">
        <DriftSeverityChip severity={event.severity} />
        <span className="font-mono text-xs text-muted-foreground">
          {event.event_type}
        </span>
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-label text-muted-foreground">Column</span>
        <span className="font-mono text-subheading">{event.column_name}</span>
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-label text-muted-foreground">Diff</span>
        <span className="font-mono text-sm">{formatDriftDiff(event)}</span>
      </div>
      <p className="text-sm">{event.description}</p>
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field
          label="Stream"
          value={
            <Link
              href={`/dis/streams/${event.stream_id}`}
              className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
            >
              {event.stream_name}
              <ExternalLink className="h-3 w-3" />
            </Link>
          }
        />
        <Field label="Tenant" value={<span className="text-sm">{event.tenant_name}</span>} />
        <Field
          label="Detected"
          value={
            <span className="text-sm text-muted-foreground">
              {formatDistanceToNow(new Date(event.detected_at), { addSuffix: true })}
            </span>
          }
        />
      </dl>
      <div className="flex flex-wrap gap-4">
        <Link
          href={`/dis/runs/${event.run_id}`}
          className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
        >
          Open run
          <ExternalLink className="h-3 w-3" />
        </Link>
        {/* Phase 5e.4c: cross-link now lands on the stream detail page
            (per-feed Alerts tab is the load-bearing scope). Updated
            from /dis/sources/[source_id]. */}
        <Link
          href={`/dis/streams/${event.stream_id}`}
          className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
        >
          View related alerts
          <ExternalLink className="h-3 w-3" />
        </Link>
      </div>
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
