"use client";

import { useTenants } from "@/lib/hooks/use-tenants";
import { cn } from "@/lib/utils";
import type { TemplateDomain, TemplateVisibility } from "@/types/dis";

// Phase 5c.5a: templates filter row. Same useFleetPersona-driven
// tenant-dropdown gating as the alerts/runs/validation surfaces.

const DOMAIN_OPTIONS: Array<{ value: TemplateDomain | "all"; label: string }> = [
  { value: "all", label: "All domains" },
  { value: "sales", label: "Sales" },
  { value: "inventory", label: "Inventory" },
  { value: "customers", label: "Customers" },
  { value: "suppliers", label: "Suppliers" },
  { value: "stores", label: "Stores" },
  { value: "products", label: "Products" },
];

const VISIBILITY_OPTIONS: Array<{ value: TemplateVisibility | "all"; label: string }> = [
  { value: "all", label: "All visibility" },
  { value: "TENANT_SHARED", label: "Shared" },
  { value: "PRIVATE", label: "Private" },
];

const SELECT_CN = cn(
  "h-9 rounded-md border border-input bg-background px-2.5 py-1 text-sm",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
  "dark:bg-input/30",
);

export type TemplatesFiltersState = {
  domain: TemplateDomain | "all";
  visibility: TemplateVisibility | "all";
  tenant_id: string;
};

type Props = {
  filters: TemplatesFiltersState;
  onChange: (next: TemplatesFiltersState) => void;
  showTenantFilter: boolean;
};

export function TemplatesFilters({ filters, onChange, showTenantFilter }: Props) {
  const tenantsQuery = useTenants();
  const tenants = tenantsQuery.data?.items ?? [];

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
      <select
        aria-label="Filter by domain"
        value={filters.domain}
        onChange={(e) =>
          onChange({ ...filters, domain: e.target.value as TemplatesFiltersState["domain"] })
        }
        className={SELECT_CN}
      >
        {DOMAIN_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <select
        aria-label="Filter by visibility"
        value={filters.visibility}
        onChange={(e) =>
          onChange({
            ...filters,
            visibility: e.target.value as TemplatesFiltersState["visibility"],
          })
        }
        className={SELECT_CN}
      >
        {VISIBILITY_OPTIONS.map((o) => (
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
