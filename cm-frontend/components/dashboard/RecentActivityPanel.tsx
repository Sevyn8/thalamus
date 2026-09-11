"use client";

import { useRouter } from "next/navigation";
import { ScrollText } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { AuditActivityCompactRow } from "@/components/audit/AuditActivityCompactRow";
import { useAuditActivities } from "@/lib/hooks/use-audit";

// Backed by the live /audit/activities feed. Persona-scoping comes from
// backend RLS: PLATFORM sees the system-wide feed, TENANT sees own-tenant
// rows only. Empty for tenants that haven't generated audit events yet
// (expected state, not an error).
//
// Row click + View all both navigate to /superadmin/audit. There is no
// in-place detail drawer from the panel; it is a preview affordance
// pointing to the full audit surface.
//
// Row layout is factored to AuditActivityCompactRow, which leverages the
// `what` field for a single-line summary and includes resource_type +
// result chips.

const ROW_LIMIT = 5;

export function RecentActivityPanel() {
  const router = useRouter();
  const query = useAuditActivities({ limit: ROW_LIMIT });
  const rows = query.data?.items ?? [];

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle>Recent activity</CardTitle>
        <button
          type="button"
          onClick={() => router.push("/superadmin/audit")}
          className="text-caption text-primary hover:underline"
        >
          View all
        </button>
      </CardHeader>
      <CardContent>
        {query.isLoading ? (
          <Skeleton variant="row" count={4} />
        ) : query.isError ? (
          <ErrorInline
            message="Could not load recent activity."
            onRetry={() => query.refetch()}
          />
        ) : rows.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-6 text-center">
            <ScrollText
              className="h-6 w-6 text-foreground-muted"
              aria-hidden="true"
            />
            <p className="text-caption text-foreground-muted">
              No recent activity yet.
            </p>
          </div>
        ) : (
          <ul className="flex flex-col">
            {rows.map((row) => (
              <AuditActivityCompactRow
                key={row.id}
                row={row}
                onClick={() => router.push("/superadmin/audit")}
              />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
