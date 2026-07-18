"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

import { PageHeader } from "@/components/shared/PageHeader";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { AlertEventStateChip } from "@/components/dis/chips/AlertEventStateChip";
import { AlertSeverityChip } from "@/components/dis/chips/AlertSeverityChip";
import { useAlertEvent } from "@/lib/dis/hooks/use-alerts";
import type { AlertEvent } from "@/types/dis";

// Phase 5c.4d-events: alert event detail. Header card + type-narrowed
// deep-link to the operational signal that fired the alert + 3-row
// state transition list. Read-only per v1 mutation-deferral pattern.

export default function AlertEventDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const query = useAlertEvent(id);

  if (query.isLoading) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Alert event" />
        <section className="px-6 py-6">
          <Skeleton variant="row" count={4} />
        </section>
      </div>
    );
  }

  if (query.error || !query.data) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Alert event" />
        <section className="flex flex-col gap-4 px-6 py-6">
          <ErrorInline message="Could not load alert event." onRetry={() => query.refetch()} />
          <Link
            href="/dis/alerts"
            className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to alerts
          </Link>
        </section>
      </div>
    );
  }

  const event = query.data;
  const trigger = triggerLink(event);

  return (
    <div className="flex flex-1 flex-col">
      <PageHeader title={event.trigger_description} subtitle={event.source_name} />
      <section className="flex flex-col gap-6 px-6 py-6">
        <Link
          href="/dis/alerts"
          className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to alerts
        </Link>

        <div className="flex flex-col gap-4 rounded-md border border-border bg-card/30 p-6">
          <div className="flex flex-wrap items-center gap-2">
            <AlertSeverityChip severity={event.severity} />
            <AlertEventStateChip state={event.state} />
            <span className="font-mono text-xs text-muted-foreground">{event.trigger_type}</span>
          </div>
          <p className="text-sm">{event.trigger_description}</p>
          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <dt className="text-label text-muted-foreground">Stream</dt>
              <dd>
                <Link
                  href={`/dis/streams/${event.stream_id}`}
                  className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
                >
                  {event.stream_name}
                  <ExternalLink className="h-3 w-3" />
                </Link>
              </dd>
            </div>
            <div>
              <dt className="text-label text-muted-foreground">Tenant</dt>
              <dd className="text-sm">{event.tenant_name}</dd>
            </div>
            <div>
              <dt className="text-label text-muted-foreground">Channel</dt>
              <dd className="text-sm">
                <span className="font-mono text-xs text-muted-foreground">{event.channel}</span>{" "}
                · {event.recipient}
              </dd>
            </div>
          </dl>
          <Link
            href={trigger.href}
            className="inline-flex w-fit items-center gap-1 text-sm text-primary hover:underline"
          >
            {trigger.label}
            <ExternalLink className="h-3 w-3" />
          </Link>
          {event.rule_id ? (
            <Link
              href={`/dis/alerts/rules/${event.rule_id}`}
              className="inline-flex w-fit items-center gap-1 text-sm text-primary hover:underline"
            >
              Configured by rule
              <ExternalLink className="h-3 w-3" />
            </Link>
          ) : null}
        </div>

        <div className="flex flex-col gap-3">
          <h2 className="text-heading">State transitions</h2>
          <ul className="flex flex-col rounded-md border border-border bg-card/20">
            <TransitionRow label="Fired" at={event.fired_at} actor={null} />
            <TransitionRow
              label="Acknowledged"
              at={event.acknowledged_at}
              actor={event.acknowledged_by_user_name}
            />
            <TransitionRow
              label="Resolved"
              at={event.resolved_at}
              actor={event.resolved_by_user_name}
            />
          </ul>
        </div>
      </section>
    </div>
  );
}

// Type-narrowed deep-link based on trigger_type. assertNever ensures
// adding a 6th trigger_type fails the build until the case is added.
// Same pattern as SourceConfigDisplay's switchboard.
function triggerLink(event: AlertEvent): { href: string; label: string } {
  switch (event.trigger_type) {
    case "FRESHNESS_STALE":
    case "FRESHNESS_CRITICAL":
      // Phase 5e.4b: freshness route is keyed by stream_id now. Old
      // fixtures populated trigger_ref_id with source_id; using
      // event.stream_id directly is the correct cross-resource link.
      // 5e.4c will retire the trigger_ref_id-for-freshness convention.
      return { href: `/dis/freshness/${event.stream_id}`, label: "Open freshness detail" };
    case "RUN_FAILURE_STREAK":
      return { href: `/dis/runs/${event.trigger_ref_id}`, label: "Open triggering run" };
    case "VALIDATION_VIOLATION_THRESHOLD":
      return {
        href: `/dis/validation/rules/${event.trigger_ref_id}`,
        label: "Open triggering rule",
      };
    case "SCHEMA_DRIFT_BREAKING":
      return {
        href: `/dis/validation/drift/${event.trigger_ref_id}`,
        label: "Open triggering drift event",
      };
    default: {
      const _exhaustive: never = event.trigger_type;
      void _exhaustive;
      return { href: `/dis/streams/${event.stream_id}`, label: "Open stream" };
    }
  }
}

function TransitionRow({
  label,
  at,
  actor,
}: {
  label: string;
  at: string | null;
  actor: string | null;
}) {
  const done = at !== null;
  return (
    <li className="flex items-center justify-between gap-3 border-b border-border px-4 py-3 last:border-b-0">
      <div className="flex flex-col gap-0.5">
        <span className={done ? "text-sm font-medium" : "text-sm text-muted-foreground italic"}>
          {label}
        </span>
        {actor ? <span className="text-caption text-muted-foreground">by {actor}</span> : null}
      </div>
      <span className="text-xs text-muted-foreground">
        {at ? formatDistanceToNow(new Date(at), { addSuffix: true }) : "—"}
      </span>
    </li>
  );
}
