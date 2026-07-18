"use client";

import { useTenants } from "@/lib/hooks/use-tenants";
import { cn } from "@/lib/utils";
import type { BackfillStatus } from "@/types/dis";

// Phase 5c.6a: backfills filter row. Same useFleetPersona-driven
// tenant-dropdown gating as the alerts/runs/validation/templates
// surfaces.

const STATUS_OPTIONS: Array<{ value: BackfillStatus | "all"; label: string }> = [
  { value: "all", label: "All statuses" },
  { value: "QUEUED", label: "Queued" },
  { value: "RUNNING", label: "Running" },
  { value: "PARTIALLY_SUCCEEDED", label: "Partially succeeded" },
  { value: "FAILED", label: "Failed" },
  { value: "SUCCEEDED", label: "Succeeded" },
  { value: "CANCELED", label: "Canceled" },
];

const SELECT_CN = cn(
  "h-9 rounded-md border border-input bg-background px-2.5 py-1 text-sm",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
  "dark:bg-input/30",
);

export type BackfillsFiltersState = {
  status: BackfillStatus | "all";
  tenant_id: string;
};

type Props = {
  filters: BackfillsFiltersState;
  onChange: (next: BackfillsFiltersState) => void;
  showTenantFilter: boolean;
};

export function BackfillsFilters({ filters, onChange, showTenantFilter }: Props) {
  const tenantsQuery = useTenants();
  const tenants = tenantsQuery.data?.items ?? [];

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
      <select
        aria-label="Filter by status"
        value={filters.status}
        onChange={(e) =>
          onChange({ ...filters, status: e.target.value as BackfillsFiltersState["status"] })
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
