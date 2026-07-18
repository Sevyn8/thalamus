"use client";

import { useTenants } from "@/lib/hooks/use-tenants";
import { cn } from "@/lib/utils";
import type { FreshnessState } from "@/types/dis";

const STATE_OPTIONS: Array<{ value: FreshnessState | "all"; label: string }> = [
  { value: "all", label: "All states" },
  { value: "CRITICAL", label: "Critical" },
  { value: "STALE", label: "Stale" },
  { value: "DELAYED", label: "Delayed" },
  { value: "FRESH", label: "Fresh" },
  { value: "UNKNOWN", label: "Unknown" },
];

const SELECT_CN = cn(
  "h-9 rounded-md border border-input bg-background px-2.5 py-1 text-sm",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
  "dark:bg-input/30",
);

export type FreshnessFiltersState = {
  state: FreshnessState | "all";
  tenant_id: string;
};

type Props = {
  filters: FreshnessFiltersState;
  onChange: (next: FreshnessFiltersState) => void;
  showTenantFilter: boolean;
};

export function FreshnessFilters({ filters, onChange, showTenantFilter }: Props) {
  const tenantsQuery = useTenants();
  const tenants = tenantsQuery.data?.items ?? [];

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
      <select
        aria-label="Filter by state"
        value={filters.state}
        onChange={(e) =>
          onChange({ ...filters, state: e.target.value as FreshnessFiltersState["state"] })
        }
        className={SELECT_CN}
      >
        {STATE_OPTIONS.map((o) => (
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
