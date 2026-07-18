"use client";

import { useTenants } from "@/lib/hooks/use-tenants";
import { cn } from "@/lib/utils";
import type { DriftEventType, DriftSeverity } from "@/types/dis";

const SEVERITY_OPTIONS: Array<{ value: DriftSeverity | "all"; label: string }> = [
  { value: "all", label: "All severities" },
  { value: "BREAKING", label: "Breaking" },
  { value: "WARNING", label: "Warning" },
  { value: "INFO", label: "Info" },
];

const EVENT_TYPE_OPTIONS: Array<{ value: DriftEventType | "all"; label: string }> = [
  { value: "all", label: "All event types" },
  { value: "COLUMN_ADDED", label: "Column added" },
  { value: "COLUMN_REMOVED", label: "Column removed" },
  { value: "TYPE_CHANGED", label: "Type changed" },
  { value: "NULLABILITY_CHANGED", label: "Nullability changed" },
];

const SELECT_CN = cn(
  "h-9 rounded-md border border-input bg-background px-2.5 py-1 text-sm",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
  "dark:bg-input/30",
);

export type DriftFiltersState = {
  severity: DriftSeverity | "all";
  event_type: DriftEventType | "all";
  // Empty string = "All tenants"; only meaningful when showTenantFilter.
  tenant_id: string;
};

type Props = {
  filters: DriftFiltersState;
  onChange: (next: DriftFiltersState) => void;
  showTenantFilter: boolean;
};

export function DriftFilters({ filters, onChange, showTenantFilter }: Props) {
  const tenantsQuery = useTenants();
  const tenants = tenantsQuery.data?.items ?? [];

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
      <select
        aria-label="Filter by severity"
        value={filters.severity}
        onChange={(e) =>
          onChange({ ...filters, severity: e.target.value as DriftFiltersState["severity"] })
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
        aria-label="Filter by event type"
        value={filters.event_type}
        onChange={(e) =>
          onChange({ ...filters, event_type: e.target.value as DriftFiltersState["event_type"] })
        }
        className={SELECT_CN}
      >
        {EVENT_TYPE_OPTIONS.map((o) => (
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
