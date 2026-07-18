"use client";

import { useTenants } from "@/lib/hooks/use-tenants";
import { cn } from "@/lib/utils";
import type { RunStatus, RunTriggeredBy } from "@/types/dis";

// Phase 5c.3b: filter row for the /dis/runs fleet page. Mirrors
// SourceFilters' inline-dropdown pattern. Tenant dropdown is platform-
// only (Anjali); for tenant personas, the page locks tenant_id from
// JWT claims and this component hides the tenant select entirely.
//
// Date range is preset-only (All time / Today / 7 days / 30 days);
// custom picker deferred to Phase 5d alongside saved-views.

const STATUS_OPTIONS: Array<{ value: RunStatus | "all"; label: string }> = [
  { value: "all", label: "All statuses" },
  { value: "QUEUED", label: "Queued" },
  { value: "RUNNING", label: "Running" },
  { value: "SUCCEEDED", label: "Succeeded" },
  { value: "FAILED", label: "Failed" },
  { value: "CANCELED", label: "Canceled" },
];

const TRIGGER_OPTIONS: Array<{ value: RunTriggeredBy | "all"; label: string }> = [
  { value: "all", label: "All triggers" },
  { value: "SCHEDULE", label: "Schedule" },
  { value: "MANUAL", label: "Manual" },
  { value: "BACKFILL", label: "Backfill" },
  { value: "API", label: "API" },
];

export type DateRangePreset = "all" | "today" | "7d" | "30d";

const DATE_OPTIONS: Array<{ value: DateRangePreset; label: string }> = [
  { value: "all", label: "All time" },
  { value: "today", label: "Today" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
];

const SELECT_CN = cn(
  "h-9 rounded-md border border-input bg-background px-2.5 py-1 text-sm",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
  "dark:bg-input/30",
);

export type RunsFiltersState = {
  status: RunStatus | "all";
  triggered_by: RunTriggeredBy | "all";
  date_range: DateRangePreset;
  // Empty string = "All tenants". Only meaningful when showTenantFilter.
  tenant_id: string;
};

// Compute started_after ISO timestamp from a preset. Anchored to
// "now" each call — fine for v1 since the result feeds a useQuery
// keyed by the params object, so re-render with the same preset
// keeps the same anchor until the page re-renders for another reason.
export function startedAfterFromPreset(
  preset: DateRangePreset,
  now: Date = new Date(),
): string | undefined {
  if (preset === "all") return undefined;
  const d = new Date(now);
  if (preset === "today") {
    d.setHours(0, 0, 0, 0);
  } else if (preset === "7d") {
    d.setDate(d.getDate() - 7);
  } else if (preset === "30d") {
    d.setDate(d.getDate() - 30);
  }
  return d.toISOString();
}

type Props = {
  filters: RunsFiltersState;
  onChange: (next: RunsFiltersState) => void;
  // True for Anjali (PLATFORM); hides tenant select for tenant personas
  // since their tenant_id is locked at the page level.
  showTenantFilter: boolean;
};

export function RunsFilters({ filters, onChange, showTenantFilter }: Props) {
  // Tenant dropdown only renders when showTenantFilter is true; the
  // hook still runs unconditionally per React rules but the result
  // is ignored when not shown.
  const tenantsQuery = useTenants();
  const tenants = tenantsQuery.data?.items ?? [];

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
      <select
        aria-label="Filter by status"
        value={filters.status}
        onChange={(e) => onChange({ ...filters, status: e.target.value as RunsFiltersState["status"] })}
        className={SELECT_CN}
      >
        {STATUS_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <select
        aria-label="Filter by trigger"
        value={filters.triggered_by}
        onChange={(e) =>
          onChange({ ...filters, triggered_by: e.target.value as RunsFiltersState["triggered_by"] })
        }
        className={SELECT_CN}
      >
        {TRIGGER_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <select
        aria-label="Filter by date range"
        value={filters.date_range}
        onChange={(e) =>
          onChange({ ...filters, date_range: e.target.value as DateRangePreset })
        }
        className={SELECT_CN}
      >
        {DATE_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {showTenantFilter ? (
        <select
          aria-label="Filter by tenant"
          value={filters.tenant_id}
          onChange={(e) => onChange({ ...filters, tenant_id: e.target.value })}
          className={SELECT_CN}
        >
          <option value="">All tenants</option>
          {tenants.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      ) : null}
    </div>
  );
}
