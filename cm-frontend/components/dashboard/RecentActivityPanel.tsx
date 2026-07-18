"use client";

import { useRouter } from "next/navigation";
import { ScrollText } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { AuditActivityCompactRow } from "@/components/audit/AuditActivityCompactRow";
import { useAuditActivities } from "@/lib/hooks/use-audit";

// Phase 5h.4 (2026-05-23): RecentActivityPanel migrated from
// pre-5h.1 audit-logs stub to the live /audit/activities feed.
// Persona-scoping comes from backend RLS: PLATFORM sees the system-
// wide feed, TENANT sees own-tenant rows only. Empty for tenants
// that haven't generated audit events yet (expected v0 state).
//
// Row click + View all both navigate to /superadmin/audit. In-place
// detail drawer from the panel is deferred — for v0 the panel is a
// preview affordance pointing to the full audit surface.
//
// Phase 5i.1 (2026-05-25): row layout factored to AuditActivityCompactRow
// which leverages the `what` field (6.16.7) for a single-line summary
// and includes resource_type + result chips.

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
