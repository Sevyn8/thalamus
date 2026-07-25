"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/shared/PageHeader";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { comingInV1 } from "@/components/shared/ComingInV1Toast";
import { ModuleSummaryCard } from "@/components/modules/ModuleSummaryCard";
import { ModuleAccessMatrix } from "@/components/modules/ModuleAccessMatrix";
import { useModuleCards, useModuleMatrix } from "@/lib/hooks/use-modules";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { hasPermission } from "@/lib/auth/permissions-check";
import { cn } from "@/lib/utils";

type FilterValue = "default" | "all" | "active" | "trial" | "suspended";

const FILTERS: { value: FilterValue; label: string }[] = [
  { value: "default", label: "Active + Trial (default)" },
  { value: "all", label: "All tenants" },
  { value: "active", label: "Active only" },
  { value: "trial", label: "Trial only" },
  { value: "suspended", label: "Suspended" },
];

// Backend's matrix accepts a single status value (Pydantic Literal),
// not arrays. TERMINATED is structurally absent from matrix row set
// — not a valid filter value (backend returns 422). The "default"
// filter collapses to no-filter (backend's row set is already non-
// TERMINATED).
type MatrixStatus = "ONBOARDING" | "TRIAL" | "ACTIVE" | "SUSPENDED";
const STATUS_BY_FILTER: Record<FilterValue, MatrixStatus | null> = {
  default: null,
  all: null,
  active: "ACTIVE",
  trial: "TRIAL",
  suspended: "SUSPENDED",
};

function isFilter(v: string | null): v is FilterValue {
  return v === "default" || v === "all" || v === "active" || v === "trial" || v === "suspended";
}

function ModulesPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const snapshot = useAuthSnapshot();

  // Phase 5h.5 (2026-05-23): Module Access has no use for TENANT
  // personas (single-tenant matrix shows one row; aggregate cards
  // are platform-wide). Sidebar nav already hides the entry under
  // 5g.1's permission gate, but direct URL navigation still resolves
  // here without a redirect. Mirror /superadmin/tenants pattern:
  // gate on the PLATFORM-only tuple (ADMIN.TENANTS.OVERRIDE.GLOBAL —
  // the same one that authorizes the toggle endpoints behind the
  // matrix) and bounce to dashboard.
  //
  // grantsLoaded guard prevents a boot-transient redirect while
  // /me/permissions is in flight (snapshot.permissions is null until
  // the fetch resolves).
  const canViewModuleAccess = hasPermission(
    snapshot,
    "ADMIN",
    "TENANTS",
    "OVERRIDE",
    "GLOBAL",
  );
  const grantsLoaded = snapshot?.permissions != null;
  useEffect(() => {
    if (grantsLoaded && !canViewModuleAccess) {
      router.replace("/superadmin/dashboard");
    }
  }, [grantsLoaded, canViewModuleAccess, router]);

  const rawFilter = searchParams.get("filter");
  const filter: FilterValue = isFilter(rawFilter) ? rawFilter : "default";

  function changeFilter(next: FilterValue) {
    const sp = new URLSearchParams(searchParams.toString());
    if (next === "default") sp.delete("filter");
    else sp.set("filter", next);
    const qs = sp.toString();
    router.replace(`/superadmin/modules${qs ? `?${qs}` : ""}`);
  }

  const summary = useModuleCards();
  const statusFilter = STATUS_BY_FILTER[filter];
  const matrix = useModuleMatrix(statusFilter ? { status: statusFilter } : undefined);

  // Suppress UI flash for personas that will be redirected. Renders
  // null during boot (permissions in flight) AND for resolved-deny
  // (TENANT). PLATFORM trades a brief blank for the loading skeleton
  // they'd have seen anyway.
  if (!canViewModuleAccess) {
    return null;
  }

  return (
    <div className="flex flex-col">
      <PageHeader
        title="Module Access"
        subtitle="Enable or disable Sevyn8 modules per tenant. Disabling instantly revokes role permissions."
      />

      <section className="px-6 py-6">
        {summary.isLoading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} variant="card" className="h-28" />
            ))}
          </div>
        ) : summary.error ? (
          <ErrorInline
            message="Could not load module summary."
            onRetry={() => summary.refetch()}
          />
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {(summary.data?.items ?? []).map((m) => (
              <ModuleSummaryCard
                key={m.module_code}
                module={m}
                onClick={() => comingInV1(`${m.module_label} detail`)}
              />
            ))}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-4 px-6 pb-12">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Tenant access</h2>
          <select
            aria-label="Filter tenants"
            value={filter}
            onChange={(e) => changeFilter(e.target.value as FilterValue)}
            className={cn(
              "h-8 min-w-[200px] rounded-md border border-input bg-background px-2.5 py-1 text-sm",
              "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
              "dark:bg-input/30",
            )}
          >
            {FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </div>

        <ModuleAccessMatrix
          rows={matrix.data?.items ?? []}
          modules={summary.data?.items ?? []}
          loading={matrix.isLoading || summary.isLoading}
          hasError={!!matrix.error || !!summary.error}
          onRetry={() => {
            void matrix.refetch();
            void summary.refetch();
          }}
        />
      </section>
    </div>
  );
}

export default function ModulesPage() {
  return (
    <Suspense fallback={null}>
      <ModulesPageInner />
    </Suspense>
  );
}
