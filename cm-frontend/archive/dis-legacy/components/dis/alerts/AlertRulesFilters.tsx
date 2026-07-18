"use client";

import { useTenants } from "@/lib/hooks/use-tenants";
import { cn } from "@/lib/utils";
import type { AlertRuleScope, AlertSeverity } from "@/types/dis";

// Phase 5c.4d-rules: filter row for /dis/alerts/rules. Mirrors the
// AlertEventsFilters shape (status / severity / scope, tenant for
// Anjali). Channel + trigger_type filters omitted in v1 — the type
// supports them and the handler accepts the params; keep the dropdown
// surface tight given the 14-fixture footprint.

const STATUS_OPTIONS: Array<{ value: "all" | "enabled" | "disabled"; label: string }> = [
  { value: "all", label: "All statuses" },
  { value: "enabled", label: "Enabled" },
  { value: "disabled", label: "Disabled" },
];

const SEVERITY_OPTIONS: Array<{ value: AlertSeverity | "all"; label: string }> = [
  { value: "all", label: "All severities" },
  { value: "CRITICAL", label: "Critical" },
  { value: "WARNING", label: "Warning" },
  { value: "INFO", label: "Info" },
];

const SCOPE_OPTIONS: Array<{ value: AlertRuleScope | "all"; label: string }> = [
  { value: "all", label: "All scopes" },
  { value: "SOURCE", label: "Source-scoped" },
  { value: "FLEET", label: "Tenant-wide" },
];

const SELECT_CN = cn(
  "h-9 rounded-md border border-input bg-background px-2.5 py-1 text-sm",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
  "dark:bg-input/30",
);

export type AlertRulesFiltersState = {
  status: "all" | "enabled" | "disabled";
  severity: AlertSeverity | "all";
  scope: AlertRuleScope | "all";
  tenant_id: string;
};

type Props = {
  filters: AlertRulesFiltersState;
  onChange: (next: AlertRulesFiltersState) => void;
  showTenantFilter: boolean;
};

export function AlertRulesFilters({ filters, onChange, showTenantFilter }: Props) {
  const tenantsQuery = useTenants();
  const tenants = tenantsQuery.data?.items ?? [];

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
      <select
        aria-label="Filter by status"
        value={filters.status}
        onChange={(e) =>
          onChange({ ...filters, status: e.target.value as AlertRulesFiltersState["status"] })
        }
        className={SELECT_CN}
      >
        {STATUS_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <select
        aria-label="Filter by severity"
        value={filters.severity}
        onChange={(e) =>
          onChange({ ...filters, severity: e.target.value as AlertRulesFiltersState["severity"] })
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
        aria-label="Filter by scope"
        value={filters.scope}
        onChange={(e) =>
          onChange({ ...filters, scope: e.target.value as AlertRulesFiltersState["scope"] })
        }
        className={SELECT_CN}
      >
        {SCOPE_OPTIONS.map((o) => (
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
