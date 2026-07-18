"use client";

import { useTenants } from "@/lib/hooks/use-tenants";
import { cn } from "@/lib/utils";
import type { AlertEventState, AlertSeverity } from "@/types/dis";

// Phase 5c.4d-events: filter row for /dis/alerts. Channel filter
// dropped per the LOC overage trim — the type still supports filtering
// by channel (handler accepts the query param), and the table column
// continues to show channel inline. UX gap: ops can't currently
// narrow by Slack vs PagerDuty from the dropdown. Re-add as polish
// before Phase 5d if it becomes a real ask; ~25 LOC delta.

const STATE_OPTIONS: Array<{ value: AlertEventState | "all"; label: string }> = [
  { value: "all", label: "All states" },
  { value: "UNRESOLVED", label: "Unresolved" },
  { value: "ACKNOWLEDGED", label: "Acknowledged" },
  { value: "RESOLVED", label: "Resolved" },
];

const SEVERITY_OPTIONS: Array<{ value: AlertSeverity | "all"; label: string }> = [
  { value: "all", label: "All severities" },
  { value: "CRITICAL", label: "Critical" },
  { value: "WARNING", label: "Warning" },
  { value: "INFO", label: "Info" },
];

export type AlertDateRangePreset = "all" | "today" | "7d" | "30d";

const DATE_OPTIONS: Array<{ value: AlertDateRangePreset; label: string }> = [
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

export type AlertEventsFiltersState = {
  state: AlertEventState | "all";
  severity: AlertSeverity | "all";
  date_range: AlertDateRangePreset;
  tenant_id: string;
};

export function firedAfterFromPreset(
  preset: AlertDateRangePreset,
  now: Date = new Date(),
): string | undefined {
  if (preset === "all") return undefined;
  const d = new Date(now);
  if (preset === "today") d.setHours(0, 0, 0, 0);
  else if (preset === "7d") d.setDate(d.getDate() - 7);
  else if (preset === "30d") d.setDate(d.getDate() - 30);
  return d.toISOString();
}

type Props = {
  filters: AlertEventsFiltersState;
  onChange: (next: AlertEventsFiltersState) => void;
  showTenantFilter: boolean;
};

export function AlertEventsFilters({ filters, onChange, showTenantFilter }: Props) {
  const tenantsQuery = useTenants();
  const tenants = tenantsQuery.data?.items ?? [];

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
      <select
        aria-label="Filter by state"
        value={filters.state}
        onChange={(e) =>
          onChange({ ...filters, state: e.target.value as AlertEventsFiltersState["state"] })
        }
        className={SELECT_CN}
      >
        {STATE_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <select
        aria-label="Filter by severity"
        value={filters.severity}
        onChange={(e) =>
          onChange({ ...filters, severity: e.target.value as AlertEventsFiltersState["severity"] })
        }
        className={SELECT_CN}
      >
        {SEVERITY_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <select
        aria-label="Filter by date range"
        value={filters.date_range}
        onChange={(e) =>
          onChange({ ...filters, date_range: e.target.value as AlertDateRangePreset })
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
