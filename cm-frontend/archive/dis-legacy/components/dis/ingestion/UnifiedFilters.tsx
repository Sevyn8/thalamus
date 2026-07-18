"use client";

import { Search } from "lucide-react";

import { Input } from "@/components/ui/input";
import { useTenants } from "@/lib/hooks/use-tenants";
import { cn } from "@/lib/utils";
import type {
  StreamDomain,
  StreamHealth,
  StreamStatus,
  SystemKind,
} from "@/types/dis";

// Phase 5e.9: unified filter bar for /dis/sources fleet view.
// Combines source-side filters (system kind) with stream-side filters
// (domain, status, health) into a single row. Tenant filter rendered
// when caller passes showTenantFilter (PLATFORM persona).
//
// Status filter scope: STREAM status only per 5e.9 Ambiguity 4
// decision — operational filtering is overwhelmingly "show me streams
// in ERROR" or "show me ACTIVE streams". Source status renders
// in-row but isn't filterable.

const SYSTEM_KIND_OPTIONS: Array<{ value: SystemKind | "all"; label: string }> = [
  { value: "all", label: "All systems" },
  { value: "CSV_SCHEDULED", label: "CSV (scheduled)" },
  { value: "SQUARE", label: "Square" },
  { value: "LIGHTSPEED", label: "Lightspeed" },
  { value: "SHOPIFY_POS", label: "Shopify POS" },
  { value: "TOAST", label: "Toast" },
  { value: "CLOVER", label: "Clover" },
  { value: "POS_API_GENERIC", label: "POS API (generic)" },
  { value: "FTP", label: "FTP" },
  { value: "REST_API_GENERIC", label: "REST API (generic)" },
];

const DOMAIN_OPTIONS: Array<{ value: StreamDomain | "all"; label: string }> = [
  { value: "all", label: "All domains" },
  { value: "sales", label: "Sales" },
  { value: "inventory", label: "Inventory" },
  { value: "customers", label: "Customers" },
  { value: "suppliers", label: "Suppliers" },
  { value: "stores", label: "Stores" },
  { value: "products", label: "Products" },
];

const STATUS_OPTIONS: Array<{ value: StreamStatus | "all"; label: string }> = [
  { value: "all", label: "All statuses" },
  { value: "ACTIVE", label: "Active" },
  { value: "PAUSED", label: "Paused" },
  { value: "ERROR", label: "Error" },
  { value: "ONBOARDING", label: "Onboarding" },
];

const HEALTH_OPTIONS: Array<{ value: StreamHealth | "all"; label: string }> = [
  { value: "all", label: "All health" },
  { value: "HEALTHY", label: "Healthy" },
  { value: "DEGRADED", label: "Degraded" },
  { value: "FAILING", label: "Failing" },
  { value: "UNKNOWN", label: "Unknown" },
];

const SELECT_CN = cn(
  "h-9 rounded-md border border-input bg-background px-2.5 py-1 text-sm",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
  "dark:bg-input/30",
);

export type UnifiedFiltersValue = {
  search: string;
  system_kind: SystemKind | "all";
  domain: StreamDomain | "all";
  status: StreamStatus | "all";
  health: StreamHealth | "all";
  tenant_id: string;
};

type Props = {
  filters: UnifiedFiltersValue;
  onChange: (next: UnifiedFiltersValue) => void;
  showTenantFilter: boolean;
};

export function UnifiedFilters({
  filters,
  onChange,
  showTenantFilter,
}: Props) {
  const tenantsQuery = useTenants();
  const tenants = tenantsQuery.data?.items ?? [];

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
      <div className="relative w-full max-w-sm">
        <Search
          className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
        <Input
          type="search"
          placeholder="Search sources & streams..."
          value={filters.search}
          onChange={(e) => onChange({ ...filters, search: e.target.value })}
          className="pl-8"
        />
      </div>
      <select
        aria-label="Filter by system kind"
        value={filters.system_kind}
        onChange={(e) =>
          onChange({
            ...filters,
            system_kind: e.target.value as UnifiedFiltersValue["system_kind"],
          })
        }
        className={SELECT_CN}
      >
        {SYSTEM_KIND_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <select
        aria-label="Filter by domain"
        value={filters.domain}
        onChange={(e) =>
          onChange({ ...filters, domain: e.target.value as UnifiedFiltersValue["domain"] })
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
        aria-label="Filter by status"
        value={filters.status}
        onChange={(e) =>
          onChange({ ...filters, status: e.target.value as UnifiedFiltersValue["status"] })
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
        aria-label="Filter by health"
        value={filters.health}
        onChange={(e) =>
          onChange({ ...filters, health: e.target.value as UnifiedFiltersValue["health"] })
        }
        className={SELECT_CN}
      >
        {HEALTH_OPTIONS.map((o) => (
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
