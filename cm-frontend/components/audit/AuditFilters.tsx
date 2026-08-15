"use client";

import { useEffect, useState } from "react";
import { Search } from "lucide-react";

import { Input } from "@/components/ui/input";
import { useTenants } from "@/lib/hooks/use-tenants";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { cn } from "@/lib/utils";
import type { AuditResourceType, AuditResultType } from "@/lib/api/audit";

const FIELD_INPUT_CLASS = cn(
  "h-9 w-full rounded-md border border-input bg-background px-2.5 py-1 text-sm",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
  "dark:bg-input/30",
);

const SELECT_CLASS = cn(FIELD_INPUT_CLASS, "appearance-none");

const STATUS_OPTIONS: { value: "" | AuditResultType; label: string }[] = [
  { value: "", label: "Any result" },
  { value: "SUCCESS", label: "Success" },
  { value: "PERMISSION_DENIED", label: "Permission denied" },
  { value: "VALIDATION_FAILED", label: "Validation failed" },
  { value: "CONFLICT", label: "Conflict" },
  { value: "INTEGRITY_VIOLATION", label: "Integrity violation" },
  { value: "INTERNAL_ERROR", label: "Internal error" },
];

// Phase 5i.1: resource_type dropdown options. Backend treats the
// parameter as an open string vocabulary; this list covers the 6
// emitters present today. New values would still 200 + filter
// correctly, they just wouldn't surface in the dropdown.
const RESOURCE_TYPE_OPTIONS: {
  value: "" | AuditResourceType;
  label: string;
}[] = [
  { value: "", label: "All resources" },
  { value: "TENANT", label: "Tenant" },
  { value: "TENANT_USER", label: "Tenant user" },
  { value: "ROLE", label: "Role" },
  { value: "MODULE_ACCESS", label: "Module access" },
  { value: "ORG_NODE", label: "Org node" },
  { value: "STORE", label: "Store" },
];

export type AuditFilterState = {
  from: string;
  to: string;
  status: string;
  scope: string;
  tenant_id: string;
  search: string;
  resource_type: string;
};

export const AUDIT_FILTER_DEFAULTS: AuditFilterState = {
  from: "",
  to: "",
  status: "",
  scope: "",
  tenant_id: "",
  search: "",
  resource_type: "",
};

export type AuditFiltersProps = {
  filters: AuditFilterState;
  onChange: (next: AuditFilterState) => void;
  showScopeFilter: boolean;
  showTenantFilter: boolean;
};

function FieldLabel({
  htmlFor,
  children,
}: {
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <label htmlFor={htmlFor} className="text-label text-foreground-muted">
      {children}
    </label>
  );
}

export function AuditFilters({
  filters,
  onChange,
  showScopeFilter,
  showTenantFilter,
}: AuditFiltersProps) {
  // Local search state so typing doesn't immediately re-fire the
  // list query. Debounced 300ms (matches Stores / Tenants pattern).
  const [searchInput, setSearchInput] = useState(filters.search);
  const debouncedSearch = useDebouncedValue(searchInput, 300);

  useEffect(() => {
    if (debouncedSearch !== filters.search) {
      onChange({ ...filters, search: debouncedSearch });
    }
  }, [debouncedSearch, filters, onChange]);

  // Reset local input if filters are externally cleared (e.g. via
  // a reset button or URL navigation).
  useEffect(() => {
    if (filters.search === "" && searchInput !== "") {
      // The rule is right that this is a render-then-render: the input paints its old
      // value and is corrected on the next pass. NOT the modal-reset shape the other
      // suppressions in this codebase carry, and there is no remount to key on here.
      // The canonical fix is to stop holding a second copy of this value: derive the
      // input from filters.search, or lift the draft state to the owner that already
      // owns the committed one. Either is a real change to how this component and its
      // parent share state, and it would land with the debounce effect above rather
      // than on its own.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSearchInput("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.search]);

  const tenantsQuery = useTenants(undefined, { enabled: showTenantFilter });
  const tenants = tenantsQuery.data?.items ?? [];

  function set<K extends keyof AuditFilterState>(
    key: K,
    value: AuditFilterState[K],
  ) {
    onChange({ ...filters, [key]: value });
  }

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-md border border-border bg-surface p-3">
      <div className="flex min-w-[200px] flex-1 flex-col gap-1">
        <FieldLabel htmlFor="audit-search">Search</FieldLabel>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-foreground-muted" />
          <Input
            id="audit-search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Actor, resource…"
            className="pl-8"
          />
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <FieldLabel htmlFor="audit-from">From</FieldLabel>
        <input
          id="audit-from"
          type="date"
          className={FIELD_INPUT_CLASS}
          value={filters.from}
          onChange={(e) => set("from", e.target.value)}
        />
      </div>

      <div className="flex flex-col gap-1">
        <FieldLabel htmlFor="audit-to">To</FieldLabel>
        <input
          id="audit-to"
          type="date"
          className={FIELD_INPUT_CLASS}
          value={filters.to}
          onChange={(e) => set("to", e.target.value)}
        />
      </div>

      <div className="flex flex-col gap-1">
        <FieldLabel htmlFor="audit-status">Result</FieldLabel>
        <select
          id="audit-status"
          className={SELECT_CLASS}
          value={filters.status}
          onChange={(e) => set("status", e.target.value)}
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1">
        <FieldLabel htmlFor="audit-resource-type">Resource</FieldLabel>
        <select
          id="audit-resource-type"
          className={SELECT_CLASS}
          value={filters.resource_type}
          onChange={(e) => set("resource_type", e.target.value)}
        >
          {RESOURCE_TYPE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {showScopeFilter ? (
        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="audit-scope">Scope</FieldLabel>
          <select
            id="audit-scope"
            className={SELECT_CLASS}
            value={filters.scope}
            onChange={(e) => set("scope", e.target.value)}
          >
            <option value="">Any scope</option>
            <option value="PLATFORM">Platform</option>
            <option value="TENANT">Tenant</option>
          </select>
        </div>
      ) : null}

      {showTenantFilter ? (
        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="audit-tenant">Tenant</FieldLabel>
          <select
            id="audit-tenant"
            className={SELECT_CLASS}
            value={filters.tenant_id}
            onChange={(e) => set("tenant_id", e.target.value)}
          >
            <option value="">Any tenant</option>
            {tenants.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </div>
      ) : null}
    </div>
  );
}
