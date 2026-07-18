"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft, ExternalLink } from "lucide-react";

import { PageHeader } from "@/components/shared/PageHeader";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { AlertRuleStatusChip } from "@/components/dis/chips/AlertRuleStatusChip";
import { AlertSeverityChip } from "@/components/dis/chips/AlertSeverityChip";
import { AlertEventsTable } from "@/components/dis/alerts/AlertEventsTable";
import { useAlertRule } from "@/lib/dis/hooks/use-alerts";
import type {
  AlertChannel,
  AlertRule,
  AlertSeverity,
  AlertTriggerType,
} from "@/types/dis";

// Phase 5c.4d-rules: alert-rule detail. Header card with the rule
// definition + a natural-language sentence + an inline events list
// scoped to this rule via the AlertEventsTable rule_id param. Read-
// only per the v1 mutation-deferral pattern.

export default function AlertRuleDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const query = useAlertRule(id);

  if (query.isLoading) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Alert rule" />
        <section className="px-6 py-6">
          <Skeleton variant="row" count={4} />
        </section>
      </div>
    );
  }

  if (query.error || !query.data) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Alert rule" />
        <section className="flex flex-col gap-4 px-6 py-6">
          <ErrorInline message="Could not load alert rule." onRetry={() => query.refetch()} />
          <BackLink />
        </section>
      </div>
    );
  }

  const rule = query.data;

  return (
    <div className="flex flex-1 flex-col">
      <PageHeader title={rule.name} subtitle={rule.tenant_name} />
      <section className="flex flex-col gap-6 px-6 py-6">
        <BackLink />

        <div className="flex flex-col gap-4 rounded-md border border-border bg-card/30 p-6">
          <div className="flex flex-wrap items-center gap-2">
            <AlertRuleStatusChip enabled={rule.enabled} />
            <AlertSeverityChip severity={rule.severity} />
            <span className="font-mono text-xs text-muted-foreground">{rule.trigger_type}</span>
          </div>
          <p className="text-sm">{formatRuleSentence(rule)}</p>
          {rule.description ? (
            <p className="text-caption text-muted-foreground">{rule.description}</p>
          ) : null}
          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field
              label="Scope"
              value={
                rule.scope === "SOURCE" && rule.stream_id ? (
                  <Link
                    href={`/dis/streams/${rule.stream_id}`}
                    className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
                  >
                    {rule.stream_name}
                    <ExternalLink className="h-3 w-3" />
                  </Link>
                ) : (
                  <span className="text-sm">Tenant-wide (any source)</span>
                )
              }
            />
            <Field
              label="Threshold"
              value={<span className="text-sm">{rule.trigger_threshold}</span>}
            />
            <Field
              label="Channel"
              value={
                <span className="text-sm">
                  <span className="font-mono text-xs text-muted-foreground">{rule.channel}</span>{" "}
                  · {rule.recipient}
                </span>
              }
            />
            <Field
              label="Recent events (30d)"
              value={
                <span
                  className={
                    rule.recent_event_count_30d > 0
                      ? "text-sm font-medium"
                      : "text-sm text-muted-foreground"
                  }
                >
                  {rule.recent_event_count_30d}
                </span>
              }
            />
            <Field
              label="Created by"
              value={
                <span className="text-sm">{rule.created_by_user_name ?? "—"}</span>
              }
            />
          </dl>
        </div>

        <div className="flex flex-col gap-3">
          <h2 className="text-heading">Recent events</h2>
          <AlertEventsTable
            context="fleet"
            params={{ rule_id: rule.id, limit: 50 }}
            emptyState={{
              title: "No events recorded for this rule",
              body: "This rule has not fired in the seeded window.",
            }}
          />
        </div>
      </section>
    </div>
  );
}

function BackLink() {
  return (
    <Link
      href="/dis/alerts/rules"
      className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="h-3.5 w-3.5" />
      Back to alert rules
    </Link>
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

// Composes a natural-language sentence from the rule's fields. Same
// assertNever exhaustiveness pattern as the AlertEvent detail's
// triggerLink — adding a 6th trigger_type fails the build until the
// case is added here too.
function formatRuleSentence(rule: AlertRule): string {
  const subject =
    rule.scope === "SOURCE" && rule.source_name
      ? rule.source_name
      : `any source in ${rule.tenant_name}`;
  const condition = formatTriggerCondition(rule.trigger_type, rule.trigger_threshold);
  const severity = formatSeverity(rule.severity);
  const channel = formatChannel(rule.channel);
  const tail = rule.enabled ? "" : " (rule is currently disabled)";
  return `When ${subject} ${condition}, send a ${severity} alert via ${channel} to ${rule.recipient}.${tail}`;
}

function formatTriggerCondition(
  trigger: AlertTriggerType,
  threshold: string,
): string {
  switch (trigger) {
    case "FRESHNESS_STALE":
      return `freshness flips to STALE (${threshold})`;
    case "FRESHNESS_CRITICAL":
      return `freshness flips to CRITICAL (${threshold})`;
    case "RUN_FAILURE_STREAK":
      return `records ${threshold}`;
    case "VALIDATION_VIOLATION_THRESHOLD":
      return `exceeds ${threshold}`;
    case "SCHEMA_DRIFT_BREAKING":
      return `encounters ${threshold}`;
    default: {
      const _exhaustive: never = trigger;
      void _exhaustive;
      return threshold;
    }
  }
}

function formatSeverity(severity: AlertSeverity): string {
  switch (severity) {
    case "CRITICAL":
      return "CRITICAL";
    case "WARNING":
      return "WARNING";
    case "INFO":
      return "INFO";
    default: {
      const _exhaustive: never = severity;
      void _exhaustive;
      return severity;
    }
  }
}

function formatChannel(channel: AlertChannel): string {
  switch (channel) {
    case "SLACK":
      return "Slack";
    case "EMAIL":
      return "email";
    case "PAGERDUTY":
      return "PagerDuty";
    case "WEBHOOK":
      return "webhook";
    default: {
      const _exhaustive: never = channel;
      void _exhaustive;
      return channel;
    }
  }
}
