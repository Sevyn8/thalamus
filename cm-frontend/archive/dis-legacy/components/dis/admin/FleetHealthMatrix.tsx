"use client";

import { useRouter } from "next/navigation";
import {
  AlertOctagon,
  AlertTriangle,
  Clock,
  GitCommitHorizontal,
} from "lucide-react";

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
import { useFleetHealth } from "@/lib/dis/hooks/use-admin-fleet";
import { cn } from "@/lib/utils";
import type { FleetHealthRow } from "@/types/dis";

// Phase 5c.8a: cross-tenant signal matrix. 4 signal columns drive
// the demo narrative: failed_runs_24h / stale_sources /
// unresolved_alerts / breaking_drift_24h. Each cell is click-through
// to the relevant fleet view (unfiltered for v1; URL-param wiring
// deferred to a polish chunk per ambiguity iv).
//
// Cell tone: red emphasis when count > 0 on these RED signals; muted
// grey for 0. Same severity-driven cell pattern as alerts/rules.

type SignalKey =
  | "failed_runs_24h"
  | "stale_sources"
  | "unresolved_alerts"
  | "breaking_drift_24h";

type SignalSpec = {
  key: SignalKey;
  label: string;
  icon: React.ReactNode;
  // Click-through destination (unfiltered for v1; future polish
  // chunk wires URL-params for tenant_id + state).
  href: string;
};

const SIGNALS: SignalSpec[] = [
  {
    key: "failed_runs_24h",
    label: "Failed runs (24h)",
    icon: <AlertOctagon className="h-4 w-4" aria-hidden="true" />,
    href: "/dis/runs",
  },
  {
    key: "stale_sources",
    label: "Stale sources",
    icon: <Clock className="h-4 w-4" aria-hidden="true" />,
    href: "/dis/freshness",
  },
  {
    key: "unresolved_alerts",
    label: "Unresolved alerts",
    icon: <AlertTriangle className="h-4 w-4" aria-hidden="true" />,
    href: "/dis/alerts",
  },
  {
    key: "breaking_drift_24h",
    label: "Breaking drift (24h)",
    icon: <GitCommitHorizontal className="h-4 w-4" aria-hidden="true" />,
    href: "/dis/validation/drift",
  },
];

export type FleetHealthMatrixProps = {
  // Search filter narrows visible rows client-side; ~7 tenants fits
  // in viewport without server-side filter.
  search: string;
};

export function FleetHealthMatrix({ search }: FleetHealthMatrixProps) {
  const query = useFleetHealth();

  if (query.isLoading) return <Skeleton variant="row" count={5} />;
  if (query.error) {
    return (
      <ErrorInline
        message="Could not load fleet health."
        onRetry={() => query.refetch()}
      />
    );
  }

  const rows = (query.data?.items ?? []).filter((r) => {
    if (!search.trim()) return true;
    return r.tenant_name.toLowerCase().includes(search.trim().toLowerCase());
  });

  if (rows.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-md border border-dashed border-border px-6 py-10 text-center">
        <h3 className="text-sm font-medium">No tenants match this search</h3>
        <p className="text-caption text-muted-foreground">
          Try a different name or clear the filter.
        </p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="px-3 text-label text-muted-foreground">Tenant</TableHead>
          {SIGNALS.map((s) => (
            <TableHead
              key={s.key}
              className="text-label text-muted-foreground text-right"
            >
              <div className="inline-flex items-center gap-1.5 text-muted-foreground">
                {s.icon}
                {s.label}
              </div>
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <FleetRow key={r.tenant_id} row={r} />
        ))}
      </TableBody>
    </Table>
  );
}

function FleetRow({ row }: { row: FleetHealthRow }) {
  const router = useRouter();
  return (
    <TableRow>
      <TableCell className="px-3 py-3">
        <div className="flex flex-col gap-0.5">
          <span className="text-sm font-medium">{row.tenant_name}</span>
          {row.tier ? (
            <span className="font-mono text-micro text-muted-foreground">{row.tier}</span>
          ) : null}
        </div>
      </TableCell>
      {SIGNALS.map((s) => {
        const count = row.signals[s.key];
        return (
          <TableCell key={s.key} className="text-right">
            <button
              type="button"
              onClick={() => router.push(s.href)}
              aria-label={`${count} ${s.label} for ${row.tenant_name} — open ${s.label} fleet`}
              className={cn(
                "inline-flex min-w-[3ch] items-center justify-center rounded-sm px-2 py-1 text-sm font-medium transition-colors",
                count > 0
                  ? "bg-red-50 text-red-700 ring-1 ring-inset ring-red-200 hover:bg-red-100 dark:bg-red-500/15 dark:text-red-300 dark:ring-red-500/30 dark:hover:bg-red-500/25"
                  : "text-muted-foreground hover:bg-surface-raised",
              )}
            >
              {count}
            </button>
          </TableCell>
        );
      })}
    </TableRow>
  );
}
