"use client";

import { useTenants } from "@/lib/hooks/use-tenants";
import { cn } from "@/lib/utils";
import type { ValidationRuleStatus, ValidationSeverity } from "@/types/dis";

const SEVERITY_OPTIONS: Array<{ value: ValidationSeverity | "all"; label: string }> = [
  { value: "all", label: "All severities" },
  { value: "ERROR", label: "Error" },
  { value: "WARNING", label: "Warning" },
  { value: "INFO", label: "Info" },
];

const STATUS_OPTIONS: Array<{ value: ValidationRuleStatus | "all"; label: string }> = [
  { value: "all", label: "All statuses" },
  { value: "ACTIVE", label: "Active" },
  { value: "DISABLED", label: "Disabled" },
];

const SELECT_CN = cn(
  "h-9 rounded-md border border-input bg-background px-2.5 py-1 text-sm",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
  "dark:bg-input/30",
);

// Phase 5c.4a: search input dropped per LOC-overage trim. Filters are
// dropdown-only for v1; rule-name search lands as polish before
// Phase 5d if it becomes a real ask. Severity + status + tenant
// (Anjali) cover the operational filter cases that matter for demo.
export type ValidationFiltersState = {
  severity: ValidationSeverity | "all";
  status: ValidationRuleStatus | "all";
  // Empty string = "All tenants"; only meaningful when showTenantFilter.
  tenant_id: string;
};

type Props = {
  filters: ValidationFiltersState;
  onChange: (next: ValidationFiltersState) => void;
  showTenantFilter: boolean;
};

export function ValidationFilters({ filters, onChange, showTenantFilter }: Props) {
  const tenantsQuery = useTenants();
  const tenants = tenantsQuery.data?.items ?? [];

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
      <select
        aria-label="Filter by severity"
        value={filters.severity}
        onChange={(e) =>
          onChange({ ...filters, severity: e.target.value as ValidationFiltersState["severity"] })
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
        aria-label="Filter by status"
        value={filters.status}
        onChange={(e) =>
          onChange({ ...filters, status: e.target.value as ValidationFiltersState["status"] })
        }
        className={SELECT_CN}
      >
        {STATUS_OPTIONS.map((o) => (
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
