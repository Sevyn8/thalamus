"use client";

import { use } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ExternalLink, Info } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

import { PageHeader } from "@/components/shared/PageHeader";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ValidationRuleStatusChip } from "@/components/dis/chips/ValidationRuleStatusChip";
import { ValidationSeverityChip } from "@/components/dis/chips/ValidationSeverityChip";
import {
  useValidationRule,
  useValidationViolations,
} from "@/lib/dis/hooks/use-validation";
import type { ValidationRule, ValidationViolation } from "@/types/dis";

// Phase 5c.4a: rule detail. Header card with rule definition + inline
// violation log. Each violation row click → /dis/runs/[run_id] so
// the user can investigate the run that produced the failing data.
//
// Read-only; rule edit lands when DIS backend supports rule mutation
// (Phase 5d or later). No edit/disable affordances in v1.

export default function ValidationRuleDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const ruleQuery = useValidationRule(id);
  const violationsQuery = useValidationViolations(id);

  if (ruleQuery.isLoading) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Validation rule" />
        <section className="px-6 py-6">
          <Skeleton variant="row" count={5} />
        </section>
      </div>
    );
  }

  if (ruleQuery.error || !ruleQuery.data) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Validation rule" />
        <section className="flex flex-col gap-4 px-6 py-6">
          <ErrorInline
            message="Could not load validation rule."
            onRetry={() => ruleQuery.refetch()}
          />
          <Link
            href="/dis/validation"
            className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to validation
          </Link>
        </section>
      </div>
    );
  }

  const rule = ruleQuery.data;
  const violations = violationsQuery.data?.items ?? [];

  return (
    <div className="flex flex-1 flex-col">
      <PageHeader title={rule.name} subtitle={rule.source_name} />
      <section className="flex flex-col gap-6 px-6 py-6">
        <Link
          href="/dis/validation"
          className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to validation
        </Link>

        <RuleHeader rule={rule} />
        <ViolationsSection
          isLoading={violationsQuery.isLoading}
          violations={violations}
        />
      </section>
    </div>
  );
}

function RuleHeader({ rule }: { rule: ValidationRule }) {
  return (
    <div className="flex flex-col gap-4 rounded-md border border-border bg-card/30 p-6">
      <div className="flex flex-wrap items-center gap-2">
        <ValidationSeverityChip severity={rule.severity} />
        <ValidationRuleStatusChip status={rule.status} />
        <span className="font-mono text-xs text-muted-foreground">
          {rule.type}
          {rule.target_column ? ` · ${rule.target_column}` : ""}
        </span>
      </div>
      <p className="text-sm">{rule.description}</p>
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {/* Phase 5d.5: explicit "Source column" label + tooltip
            disambiguates that rule.target_column is a raw source-feed
            column, NOT a canonical-field reference. Canonical mapping
            happens downstream at upload confirmation via
            UploadDetail.column_mappings[]. Direct canonical-field
            cross-link deferred — see BUILD_PLAN 5d.5 closeout +
            backend request for `canonical_field_id` on
            ValidationRule. */}
        <Field
          label={
            <span className="inline-flex items-center gap-1">
              Source column
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Info
                      aria-label="Source column explanation"
                      className="h-3 w-3 cursor-help text-muted-foreground"
                    />
                  }
                />
                <TooltipContent>
                  Raw column from the source feed. The canonical-field
                  mapping is set during upload confirmation in the
                  source&apos;s Mappings review.
                </TooltipContent>
              </Tooltip>
            </span>
          }
          value={
            rule.target_column ? (
              <span className="font-mono text-sm">{rule.target_column}</span>
            ) : (
              <span className="text-sm text-muted-foreground">—</span>
            )
          }
        />
        <Field
          label="Stream"
          value={
            <Link
              href={`/dis/streams/${rule.stream_id}`}
              className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
            >
              {rule.stream_name}
              <ExternalLink className="h-3 w-3" />
            </Link>
          }
        />
        <Field label="Tenant" value={<span className="text-sm">{rule.tenant_name}</span>} />
        <Field
          label="Recent violations"
          value={
            <span
              className={
                rule.recent_violation_count > 0
                  ? "text-sm font-medium text-danger"
                  : "text-sm text-muted-foreground"
              }
            >
              {rule.recent_violation_count}
            </span>
          }
        />
      </dl>
      {/* Phase 5e.4c: cross-link now lands on the stream detail page
          (per-feed Alerts tab is the load-bearing scope). Updated
          from /dis/sources/[source_id]. */}
      <Link
        href={`/dis/streams/${rule.stream_id}`}
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
}: {
  label: React.ReactNode;
  value: React.ReactNode;
}) {
  return (
    <div>
      <dt className="text-label text-muted-foreground">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function ViolationsSection({
  isLoading,
  violations,
}: {
  isLoading: boolean;
  violations: ValidationViolation[];
}) {
  const router = useRouter();
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-heading">Recent violations</h2>
      {isLoading ? (
        <Skeleton variant="row" count={3} />
      ) : violations.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border px-6 py-10 text-center">
          <p className="text-sm font-medium">No violations recorded</p>
          <p className="text-caption text-muted-foreground">
            This rule has not flagged any rows in recent runs.
          </p>
        </div>
      ) : (
        <ul className="flex flex-col rounded-md border border-border bg-card/20">
          {violations.map((v) => (
            <li
              key={v.id}
              onClick={() => router.push(`/dis/runs/${v.run_id}`)}
              className="flex flex-col gap-1 border-b border-border px-4 py-3 last:border-b-0 cursor-pointer hover:bg-surface-raised transition-colors duration-150"
            >
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <span className="font-mono">Row {v.row_index}</span>
                <span>·</span>
                <span>{formatDistanceToNow(new Date(v.created_at), { addSuffix: true })}</span>
              </div>
              <p className="text-sm">{v.message}</p>
              <p className="truncate font-mono text-xs text-muted-foreground" title={v.value}>
                {v.value}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
