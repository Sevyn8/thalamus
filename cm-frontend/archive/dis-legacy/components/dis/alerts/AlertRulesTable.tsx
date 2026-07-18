"use client";

import { useRouter } from "next/navigation";

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
import { AlertRuleStatusChip } from "@/components/dis/chips/AlertRuleStatusChip";
import { AlertSeverityChip } from "@/components/dis/chips/AlertSeverityChip";
import { useAlertRules } from "@/lib/dis/hooks/use-alerts";
import type { AlertRule, AlertRuleListParams } from "@/types/dis";

// Phase 5c.4d-rules: alert-rules table. Fleet-only in v1 (per-source
// rules tab not part of the rules chunk; the per-source Alerts tab
// shows events, where the user can drill into a specific event to
// reach its configuring rule via the "Configured by rule" link).
//
// `context` kept as a future-proofing slot consistent with the
// AlertEventsTable / ValidationRulesTable shape; v1 only renders the
// "fleet" variant. Adding "source" later is a column-set toggle, not
// a structural change.

type Context = "fleet";

type Props = {
  context: Context;
  params?: AlertRuleListParams;
  emptyState?: { title: string; body?: string };
};

export function AlertRulesTable({ context, params, emptyState }: Props) {
  const finalParams: AlertRuleListParams = {
    ...(params ?? {}),
    limit: params?.limit ?? 50,
  };
  const query = useAlertRules(finalParams);

  if (query.isLoading) return <Skeleton variant="row" count={5} />;
  if (query.error) {
    return (
      <ErrorInline
        message="Could not load alert rules."
        onRetry={() => query.refetch()}
      />
    );
  }
  const items = query.data?.items ?? [];
  if (items.length === 0) return <RulesEmptyState context={context} override={emptyState} />;
  return <RulesTableInner rules={items} />;
}

function RulesTableInner({ rules }: { rules: AlertRule[] }) {
  const router = useRouter();
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="px-3 text-label text-muted-foreground">Status</TableHead>
          <TableHead className="text-label text-muted-foreground">Severity</TableHead>
          <TableHead className="text-label text-muted-foreground">Rule</TableHead>
          <TableHead className="text-label text-muted-foreground">Scope</TableHead>
          <TableHead className="text-label text-muted-foreground">Tenant</TableHead>
          <TableHead className="text-label text-muted-foreground">Channel</TableHead>
          <TableHead className="text-label text-muted-foreground text-right">
            Recent events (30d)
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rules.map((r) => (
          <TableRow
            key={r.id}
            onClick={() => router.push(`/dis/alerts/rules/${r.id}`)}
            className="cursor-pointer"
          >
            <TableCell className="px-3 py-3">
              <AlertRuleStatusChip enabled={r.enabled} />
            </TableCell>
            <TableCell>
              <AlertSeverityChip severity={r.severity} />
            </TableCell>
            <TableCell>
              <div className="flex min-w-0 flex-col gap-1">
                <span className="truncate text-sm font-medium" title={r.name}>
                  {r.name}
                </span>
                <span className="font-mono text-xs text-muted-foreground">
                  {r.trigger_type}
                </span>
              </div>
            </TableCell>
            <TableCell>
              <div className="flex flex-col gap-0.5">
                <span className="text-sm">
                  {r.scope === "FLEET" ? "Tenant-wide" : "Source"}
                </span>
                <span className="truncate text-caption text-muted-foreground">
                  {r.scope === "SOURCE" ? r.source_name : "(any source)"}
                </span>
              </div>
            </TableCell>
            <TableCell>
              <span className="text-sm">{r.tenant_name}</span>
            </TableCell>
            <TableCell>
              <div className="flex flex-col gap-0.5">
                <span className="font-mono text-xs text-muted-foreground">{r.channel}</span>
                <span className="truncate text-xs">{r.recipient}</span>
              </div>
            </TableCell>
            <TableCell className="text-right">
              <span
                className={
                  r.recent_event_count_30d > 0
                    ? "text-sm font-medium"
                    : "text-sm text-muted-foreground"
                }
              >
                {r.recent_event_count_30d}
              </span>
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
  void context;
  const title = override?.title ?? "No alert rules match these filters";
  const body = override?.body ?? "Try widening the status or severity filter.";
  return (
    <div className="flex flex-col items-center gap-3 rounded-md border border-dashed border-border px-6 py-10 text-center">
      <h3 className="text-sm font-medium">{title}</h3>
      <p className="text-caption text-muted-foreground">{body}</p>
    </div>
  );
}
