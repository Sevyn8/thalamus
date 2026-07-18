"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { hasAnyScope } from "@/lib/auth/permissions-check";
import { useAuditActivities } from "@/lib/hooks/use-audit";
import { useCursorPagination } from "@/lib/hooks/use-cursor-pagination";
import { useUrlFilters } from "@/lib/hooks/use-url-filters";
import { PageHeader } from "@/components/shared/PageHeader";
import { EmptyState } from "@/components/shared/EmptyState";
import { Button } from "@/components/ui/button";
import {
  AuditFilters,
  AUDIT_FILTER_DEFAULTS,
  type AuditFilterState,
} from "@/components/audit/AuditFilters";
import { AuditActivitiesTable } from "@/components/audit/AuditActivitiesTable";
import { AuditActivityDetailDrawer } from "@/components/audit/AuditActivityDetailDrawer";
import type {
  AuditListParams,
  AuditResourceType,
  AuditResultType,
  AuditRowScope,
} from "@/lib/api/audit";

const PAGE_SIZE = 25;

// Date inputs come in as "YYYY-MM-DD"; backend expects ISO datetimes.
// `from` is start-of-day, `to` is end-of-day so date-range filters
// are inclusive on both ends.
function dateToFromIso(yyyymmdd: string): string | undefined {
  if (!yyyymmdd) return undefined;
  return `${yyyymmdd}T00:00:00Z`;
}
function dateToToIso(yyyymmdd: string): string | undefined {
  if (!yyyymmdd) return undefined;
  return `${yyyymmdd}T23:59:59.999Z`;
}

function buildListParams(
  filters: AuditFilterState,
  cursor: string | undefined,
): AuditListParams {
  const params: AuditListParams = { limit: PAGE_SIZE };
  if (cursor) params.cursor = cursor;
  const from = dateToFromIso(filters.from);
  const to = dateToToIso(filters.to);
  if (from) params.from = from;
  if (to) params.to = to;
  if (filters.status) params.status = filters.status as AuditResultType;
  if (filters.scope) params.scope = filters.scope as AuditRowScope;
  if (filters.tenant_id) params.tenant_id = filters.tenant_id;
  if (filters.search) params.search = filters.search;
  if (filters.resource_type) {
    params.resource_type = filters.resource_type as AuditResourceType;
  }
  return params;
}

function AuditPageInner() {
  const snapshot = useAuthSnapshot();
  const isTenantPersona = snapshot?.user?.userType === "TENANT";
  const canViewAudit = hasAnyScope(snapshot, "ADMIN", "AUDIT_LOG", "VIEW");

  const [filters, setFilters] = useUrlFilters<AuditFilterState>(
    AUDIT_FILTER_DEFAULTS,
    "/superadmin/audit",
  );

  const pagination = useCursorPagination();
  const { cursor, canGoPrev, goNext, goPrev, reset } = pagination;

  // Reset cursor when filters change. Track a stringified copy so
  // we only reset on an actual change, not on every render.
  const lastFiltersRef = useRef(filters);
  useEffect(() => {
    const a = JSON.stringify(lastFiltersRef.current);
    const b = JSON.stringify(filters);
    if (a !== b) {
      lastFiltersRef.current = filters;
      reset();
    }
  }, [filters, reset]);

  const params = useMemo(
    () => buildListParams(filters, cursor),
    [filters, cursor],
  );
  const listQuery = useAuditActivities(params);

  const [selectedActivityId, setSelectedActivityId] = useState<string | null>(
    null,
  );

  if (!canViewAudit) {
    return (
      <>
        <PageHeader title="Audit Log" />
        <EmptyState
          title="No access"
          body="You do not have permission to view the audit log."
        />
      </>
    );
  }

  const rows = listQuery.data?.items ?? [];
  const hasMore = listQuery.data?.pagination.has_more ?? false;
  const nextCursor = listQuery.data?.pagination.next_cursor ?? null;

  return (
    <>
      <PageHeader
        title="Audit Log"
        subtitle={
          isTenantPersona
            ? "Activity within your organization — actions, lifecycle events, denials."
            : "Cross-tenant activity stream — admin actions, lifecycle events, denials."
        }
      />

      <div className="flex flex-col gap-4">
        <AuditFilters
          filters={filters}
          onChange={setFilters}
          showScopeFilter={!isTenantPersona}
          showTenantFilter={!isTenantPersona}
        />

        <AuditActivitiesTable
          rows={rows}
          isLoading={listQuery.isLoading}
          isError={listQuery.isError}
          errorMessage={
            listQuery.error instanceof Error
              ? listQuery.error.message
              : undefined
          }
          onRetry={() => listQuery.refetch()}
          showScope={!isTenantPersona}
          showTenant={!isTenantPersona}
          onSelectRow={setSelectedActivityId}
        />

        {rows.length > 0 ? (
          <div className="flex items-center justify-end gap-2">
            <Button
              variant="outline"
              onClick={goPrev}
              disabled={!canGoPrev || listQuery.isFetching}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              onClick={() => goNext(nextCursor)}
              disabled={!hasMore || listQuery.isFetching}
            >
              Next
            </Button>
          </div>
        ) : null}
      </div>

      <AuditActivityDetailDrawer
        activityId={selectedActivityId}
        open={selectedActivityId !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedActivityId(null);
        }}
      />
    </>
  );
}

export default function AuditPage() {
  return (
    <Suspense fallback={null}>
      <AuditPageInner />
    </Suspense>
  );
}
