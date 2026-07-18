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
import { ValidationRuleStatusChip } from "@/components/dis/chips/ValidationRuleStatusChip";
import { ValidationSeverityChip } from "@/components/dis/chips/ValidationSeverityChip";
import { useValidationRules } from "@/lib/dis/hooks/use-validation";
import type { ValidationListParams, ValidationRule } from "@/types/dis";

// Phase 5c.4a: shared validation-rules table for the per-source tab
// + the fleet view. context controls column set:
//   - "source": omits Source / Tenant cols (already scoped)
//   - "stream": same column treatment as "source" (Phase 5e.4b — the
//               new Stream detail page scopes to one feed; columns
//               omit Source/Tenant for the same reason). Caller passes
//               streamId; table filters via stream_id query param.
//   - "fleet":  includes Source + Tenant cols
//
// Empty state per A viii: "No validation rules for this source yet."
// (literal, no conditional rendering).

type Context = "source" | "stream" | "fleet";

type Props = {
  context: Context;
  sourceId?: string;
  streamId?: string;
  params?: ValidationListParams;
  emptyState?: { title: string; body?: string };
};

export function ValidationRulesTable({
  context,
  sourceId,
  streamId,
  params,
  emptyState,
}: Props) {
  const finalParams: ValidationListParams = {
    ...(params ?? {}),
    ...(sourceId ? { source_id: sourceId } : {}),
    ...(streamId ? { stream_id: streamId } : {}),
    limit: params?.limit ?? 50,
  };
  const query = useValidationRules(finalParams);

  if (query.isLoading) return <Skeleton variant="row" count={5} />;
  if (query.error) {
    return (
      <ErrorInline
        message="Could not load validation rules."
        onRetry={() => query.refetch()}
      />
    );
  }
  const items = query.data?.items ?? [];
  if (items.length === 0) return <RulesEmptyState context={context} override={emptyState} />;
  return <RulesTableInner context={context} rules={items} />;
}

function RulesTableInner({ context, rules }: { context: Context; rules: ValidationRule[] }) {
  const router = useRouter();
  const showSourceCols = context === "fleet";
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="px-3 text-label text-muted-foreground">Severity</TableHead>
          <TableHead className="text-label text-muted-foreground">Rule</TableHead>
          {showSourceCols ? (
            <>
              <TableHead className="text-label text-muted-foreground">Source</TableHead>
              <TableHead className="text-label text-muted-foreground">Tenant</TableHead>
            </>
          ) : null}
          <TableHead className="text-label text-muted-foreground">Status</TableHead>
          <TableHead className="text-label text-muted-foreground text-right">Recent violations</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rules.map((r) => (
          <TableRow
            key={r.id}
            onClick={() => router.push(`/dis/validation/rules/${r.id}`)}
            className="cursor-pointer"
          >
            <TableCell className="px-3 py-3">
              <ValidationSeverityChip severity={r.severity} />
            </TableCell>
            <TableCell>
              <div className="flex min-w-0 flex-col gap-1">
                <span className="truncate text-sm font-medium">{r.name}</span>
                <span className="font-mono text-xs text-muted-foreground">
                  {r.type}
                  {r.target_column ? ` · ${r.target_column}` : ""}
                </span>
              </div>
            </TableCell>
            {showSourceCols ? (
              <>
                <TableCell>
                  <span className="truncate text-sm">{r.source_name}</span>
                </TableCell>
                <TableCell>
                  <span className="text-sm">{r.tenant_name}</span>
                </TableCell>
              </>
            ) : null}
            <TableCell>
              <ValidationRuleStatusChip status={r.status} />
            </TableCell>
            <TableCell className="text-right">
              <div className="flex flex-col items-end gap-0.5">
                <span
                  className={
                    r.recent_violation_count > 0
                      ? "text-sm font-medium text-danger"
                      : "text-sm text-muted-foreground"
                  }
                >
                  {r.recent_violation_count}
                </span>
                {r.last_violation_at ? (
                  <span className="text-micro text-muted-foreground">
                    {formatDistanceToNow(new Date(r.last_violation_at), { addSuffix: true })}
                  </span>
                ) : null}
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function RulesEmptyState({
  context,
  override,
}: {
  context: Context;
  override?: { title: string; body?: string };
}) {
  const title =
    override?.title ??
    (context === "source"
      ? "No validation rules for this source yet."
      : context === "stream"
        ? "No validation rules for this stream yet."
        : "No validation rules match these filters");
  const body =
    override?.body ??
    (context === "fleet"
      ? "Try widening the severity filter."
      : undefined);
  return (
    <div className="flex flex-col items-center gap-3 rounded-md border border-dashed border-border px-6 py-10 text-center">
      <h3 className="text-sm font-medium">{title}</h3>
      {body ? <p className="text-caption text-muted-foreground">{body}</p> : null}
    </div>
  );
}
