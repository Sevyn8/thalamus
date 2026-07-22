"use client";

import { useRouter } from "next/navigation";
import {
  Boxes,
  Building2,
  DollarSign,
  Lock,
  Shield,
  Store,
  Users,
} from "lucide-react";

import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { KpiCard } from "@/components/dashboard/KpiCard";
import { TopTenantsPanel } from "@/components/dashboard/TopTenantsPanel";
import { RecentActivityPanel } from "@/components/dashboard/RecentActivityPanel";
import { useFleetStats, useGovernanceStats } from "@/lib/hooks/use-dashboard";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { hasPermission } from "@/lib/auth/permissions-check";
import { cn } from "@/lib/utils";
import type { DeltaBlock, UnavailableReason } from "@/types/api";

// Phase 5e.4: rewritten to consume Sanjeev's two card-shaped
// dashboard endpoints. Split into Fleet metrics + Governance posture
// sections; mapping converts response cards to KpiCard props
// (delta-block to display string, mrr value-string to currency).

// Friendly-text for the v0 unavailable_reason vocabulary. Falls back
// to raw enum on unknown values per ambiguity vi (defensive against
// backend adding a 4th reason before frontend updates the map).
const UNAVAILABLE_TEXT: Record<UnavailableReason, string> = {
  approvals_table_not_built: "Approvals data coming soon",
  audit_logs_or_guardrails_not_wired: "Backend wiring in progress",
  custom_role_creation_not_shipped: "Custom role creation post-v0",
};

function unavailableTextFor(reason: string | null | undefined): string | undefined {
  if (!reason) return undefined;
  return (UNAVAILABLE_TEXT as Record<string, string>)[reason] ?? reason;
}

// DeltaBlock → display string. Backend ships structured deltas;
// frontend renders as "↗ +N last <window>" or "↘ -N last <window>".
function formatDelta(d: DeltaBlock | null | undefined): string | undefined {
  if (!d || !d.available || d.value === null) return undefined;
  const arrow = d.direction === "up" ? "↗" : d.direction === "down" ? "↘" : "→";
  const sign = d.value > 0 ? "+" : "";
  const window = d.window ? ` last ${d.window}` : "";
  return `${arrow} ${sign}${d.value}${window}`;
}

// Currency format for mrr_aggregated.value (string, 2 decimals from
// backend). "$308,100.00" with comma separators.
function formatCurrency(v: string, currency: string): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return `${currency} ${v}`;
  const symbol = currency === "USD" ? "$" : `${currency} `;
  return `${symbol}${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function DashboardHeader({
  title,
  subtitle,
}: {
  title: string;
  subtitle: string;
}) {
  return (
    <div className="flex flex-col gap-2 border-b border-border px-6 py-6 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-col gap-1">
        <h1 className="text-display">{title}</h1>
        <p className="text-sm text-muted-foreground">{subtitle}</p>
      </div>
      <div className="flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/5 dark:text-emerald-300">
        <span className="h-2 w-2 rounded-full bg-emerald-600 dark:bg-emerald-400" aria-hidden="true" />
        All systems operational
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const snapshot = useAuthSnapshot();
  const fleet = useFleetStats();
  const governance = useGovernanceStats();

  // Phase 5g.1: fleet + governance endpoints are multi-audience and
  // backend auto-scopes the response (sub_text re-labels per JWT), so
  // both render unchanged for PLATFORM + TENANT. TopTenantsPanel calls
  // GET /api/v1/tenants (cross-tenant list) which requires VIEW.GLOBAL
  // — hide for TENANT-OWNER so the panel doesn't render with a 403.
  // RecentActivityPanel is FeaturePending (audit-log backend not
  // shipped); stays for both audiences.
  const canSeeCrossTenant = hasPermission(
    snapshot,
    "ADMIN",
    "TENANTS",
    "VIEW",
    "GLOBAL",
  );

  // Phase 5g.1.2: persona-aware heading copy. PLATFORM keeps the
  // existing fleet-wide framing; TENANT-OWNER sees an org-scoped
  // framing that mirrors the sidebar branding ("Admin" + tenant
  // name). Cosmetic only — access control lives in the permission
  // filters above, not in the heading.
  const isTenantHeader = snapshot?.user?.userType === "TENANT";
  const tenantName = snapshot?.user?.tenantName;
  const headerTitle = isTenantHeader ? "Admin Dashboard" : "Superadmin Dashboard";
  const headerSubtitle = !isTenantHeader
    ? "Govern every tenant, module, role and approval rail across Cortex."
    : tenantName
      ? `Manage users, stores, and access for ${tenantName}.`
      : "Manage your tenant's users, stores, and access.";

  const isLoading = fleet.isLoading || governance.isLoading;
  const hasError = !!fleet.error || !!governance.error;

  return (
    <div className="flex flex-col">
      <DashboardHeader title={headerTitle} subtitle={headerSubtitle} />

      <section className="flex flex-col gap-3 px-6 py-6">
        <h2 className="text-label uppercase tracking-wider text-muted-foreground">
          Fleet metrics
        </h2>
        {isLoading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} variant="card" className="h-32" />
            ))}
          </div>
        ) : hasError ? (
          <ErrorInline
            message="Could not load fleet metrics."
            onRetry={() => fleet.refetch()}
          />
        ) : fleet.data ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <KpiCard
              icon={<Building2 />}
              iconTone="blue"
              label="Active tenants"
              metric={`${fleet.data.active_tenants.value} / ${fleet.data.active_tenants.total}`}
              subtext={fleet.data.active_tenants.sub_text}
              delta={formatDelta(fleet.data.active_tenants.delta)}
              available={fleet.data.active_tenants.available}
              onClick={() =>
                router.push("/superadmin/tenants?status=ACTIVE")
              }
            />
            <KpiCard
              icon={<Users />}
              iconTone="purple"
              label={isTenantHeader ? "Users" : "Platform users"}
              metric={fleet.data.platform_users.value.toLocaleString()}
              subtext={fleet.data.platform_users.sub_text}
              delta={formatDelta(fleet.data.platform_users.delta)}
              available={fleet.data.platform_users.available}
              onClick={() => router.push("/superadmin/users")}
            />
            <KpiCard
              icon={<Store />}
              iconTone="teal"
              label="Stores under mgmt"
              metric={fleet.data.stores.value.toLocaleString()}
              subtext={fleet.data.stores.sub_text}
              available={fleet.data.stores.available}
              onClick={() => router.push("/superadmin/org")}
            />
            <KpiCard
              icon={<DollarSign />}
              iconTone="green"
              label="MRR"
              metric={formatCurrency(
                fleet.data.mrr_aggregated.value,
                fleet.data.mrr_aggregated.currency,
              )}
              subtext={fleet.data.mrr_aggregated.sub_text}
              delta={formatDelta(fleet.data.mrr_aggregated.delta)}
              available={fleet.data.mrr_aggregated.available}
              onClick={() =>
                router.push("/superadmin/tenants?sort=-monthly_revenue_usd")
              }
            />
          </div>
        ) : null}
      </section>

      <section className="flex flex-col gap-3 px-6 pb-6">
        <h2 className="text-label uppercase tracking-wider text-muted-foreground">
          Governance posture
        </h2>
        {isLoading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} variant="card" className="h-32" />
            ))}
          </div>
        ) : hasError ? (
          <ErrorInline
            message="Could not load governance posture."
            onRetry={() => governance.refetch()}
          />
        ) : governance.data ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {/* Phase 5g.1.3: "Guardrails fired (24h)" KPI removed
                alongside the surface. "Pending approvals" stays but
                routes to /approvals (the stub surface) since the
                /superadmin/guardrails destination is gone. */}
            <KpiCard
              icon={<Shield />}
              iconTone="orange"
              label="Pending approvals"
              metric={String(governance.data.pending_approvals.value)}
              subtext={governance.data.pending_approvals.sub_text}
              available={governance.data.pending_approvals.available}
              unavailableText={unavailableTextFor(
                governance.data.pending_approvals.unavailable_reason,
              )}
              onClick={() => router.push("/approvals")}
            />
            <KpiCard
              icon={<Lock />}
              iconTone="purple"
              label="Custom roles"
              metric={String(governance.data.custom_roles.value)}
              subtext={governance.data.custom_roles.sub_text}
              available={governance.data.custom_roles.available}
              unavailableText={unavailableTextFor(
                governance.data.custom_roles.unavailable_reason,
              )}
              onClick={() => router.push("/superadmin/roles")}
            />
            <KpiCard
              icon={<Boxes />}
              iconTone="teal"
              label="Modules deployed"
              metric={String(governance.data.modules_deployed.value)}
              subtext={governance.data.modules_deployed.sub_text}
              available={governance.data.modules_deployed.available}
              onClick={() => router.push("/superadmin/modules")}
            />
          </div>
        ) : null}
      </section>

      <section
        className={cn(
          "grid grid-cols-1 gap-6 px-6 pb-12",
          canSeeCrossTenant && "lg:grid-cols-2",
        )}
      >
        {canSeeCrossTenant ? <TopTenantsPanel /> : null}
        <RecentActivityPanel />
      </section>
    </div>
  );
}
