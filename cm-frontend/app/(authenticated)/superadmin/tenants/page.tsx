"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AnimatePresence } from "framer-motion";
import { Search } from "lucide-react";
import { toast } from "sonner";

import { useCanDo } from "@/lib/auth/use-me-can-do";

import { PageHeader } from "@/components/shared/PageHeader";
import { Input } from "@/components/ui/input";
import { Tabs, TabsIndicator, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { EmptyState } from "@/components/shared/EmptyState";
import { TenantCard } from "@/components/tenants/TenantCard";
import { TenantDetailDrawer } from "@/components/tenants/TenantDetailDrawer";
import { useTenants, useTenantStats } from "@/lib/hooks/use-tenants";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { hasPermission } from "@/lib/auth/permissions-check";
import type { TenantTier } from "@/types/api";

type TabValue = "all" | TenantTier;

const TABS: { value: TabValue; label: string }[] = [
  { value: "all", label: "All" },
  { value: "ENTERPRISE", label: "Enterprise" },
  { value: "MID_MARKET", label: "Mid-Market" },
  { value: "SMB", label: "SMB" },
  { value: "SINGLE_STORE", label: "Single-Store" },
];

const TIER_VALUES: TenantTier[] = ["ENTERPRISE", "MID_MARKET", "SMB", "SINGLE_STORE"];

function isTier(v: string | null): v is TenantTier {
  return v !== null && (TIER_VALUES as string[]).includes(v);
}

function TenantsPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const snapshot = useAuthSnapshot();

  // Phase 5g.1: tenant-list surface requires ADMIN.TENANTS.VIEW.GLOBAL.
  // TENANT-OWNER personas redirect to their dashboard rather than land
  // on a 403-fetching page (cleaner than a soft-403 message; their
  // dashboard already shows tenant-scoped stats).
  //
  // Fail-closed during boot: snapshot.permissions is null while
  // /me/permissions is in flight, so `canList` starts false and would
  // redirect. Guarded by `snapshot?.permissions != null` to wait for
  // grants to populate before deciding — boot transient stays on the
  // page, only resolved-false triggers the redirect.
  const canList = hasPermission(
    snapshot,
    "ADMIN",
    "TENANTS",
    "VIEW",
    "GLOBAL",
  );
  const grantsLoaded = snapshot?.permissions != null;

  useEffect(() => {
    if (grantsLoaded && !canList) {
      router.replace("/superadmin/dashboard");
    }
  }, [grantsLoaded, canList, router]);

  const urlSearch = searchParams.get("search") ?? "";
  const urlTier = searchParams.get("tier");
  const urlTab: TabValue = isTier(urlTier) ? urlTier : "all";
  const selectedId = searchParams.get("tenant");

  const [search, setSearch] = useState(urlSearch);
  const debouncedSearch = useDebouncedValue(search, 300);

  // Phase 5f.W.2: eager /me/can-do pre-flight on the provision-tenant
  // tuple. Cache populates on mount; the click handler reads from
  // cache. Tuple is ADMIN.TENANTS.CONFIGURE.GLOBAL because v0 enum
  // has CONFIGURE but not SUSPEND/PROVISION — Sanjeev queue tracks
  // an ask for PermissionAction enum granularity. Anjali's grant
  // set in mocks/handlers/me.ts includes this tuple → allowed:true.
  const canProvisionTenant = useCanDo(
    "ADMIN",
    "TENANTS",
    "CONFIGURE",
    "GLOBAL",
  );

  // Slice 6: the "+ Provision tenant" modal is retired in favour of the
  // onboarding wizard. Same CONFIGURE.GLOBAL pre-check; on allow, route to
  // the new-tenant wizard entry rather than opening the modal.
  function onOnboardClick() {
    if (canProvisionTenant.data?.allowed === false) {
      toast.error("You don't have permission to onboard clients.");
      return;
    }
    router.push("/superadmin/tenants/onboard");
  }

  useEffect(() => {
    if (debouncedSearch === urlSearch) return;
    const sp = new URLSearchParams(searchParams.toString());
    if (debouncedSearch) sp.set("search", debouncedSearch);
    else sp.delete("search");
    const qs = sp.toString();
    router.replace(`/superadmin/tenants${qs ? `?${qs}` : ""}`);
  }, [debouncedSearch, urlSearch, searchParams, router]);

  function changeTier(next: TabValue) {
    const sp = new URLSearchParams(searchParams.toString());
    if (next === "all") sp.delete("tier");
    else sp.set("tier", next);
    const qs = sp.toString();
    router.replace(`/superadmin/tenants${qs ? `?${qs}` : ""}`);
  }

  function openTenant(id: string) {
    const sp = new URLSearchParams(searchParams.toString());
    sp.set("tenant", id);
    router.push(`/superadmin/tenants?${sp.toString()}`);
  }

  function closeDrawer() {
    const sp = new URLSearchParams(searchParams.toString());
    sp.delete("tenant");
    const qs = sp.toString();
    router.replace(`/superadmin/tenants${qs ? `?${qs}` : ""}`);
  }

  // Gate fetches on the grant. Avoids a noisy 403 round-trip during
  // the brief window between page mount and the useEffect redirect.
  const tenantsQuery = useTenants(
    {
      search: debouncedSearch || undefined,
      tier: urlTab !== "all" ? urlTab : undefined,
    },
    { enabled: canList },
  );
  const statsQuery = useTenantStats({ enabled: canList });

  const subtitle = statsQuery.data
    ? `${statsQuery.data.total_tenants.toLocaleString()} client organizations · ${statsQuery.data.total_stores.toLocaleString()} stores`
    : "Loading...";

  const items = tenantsQuery.data?.items ?? [];

  return (
    <div className="flex flex-col">
      <PageHeader
        title="Tenants"
        subtitle={subtitle}
        primaryAction={{
          label: "+ Onboard client",
          onClick: onOnboardClick,
        }}
      />

      <section className="flex flex-col gap-4 px-6 pt-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="relative w-full max-w-sm">
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              type="search"
              placeholder="Search tenants..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8"
            />
          </div>
          <Tabs value={urlTab} onValueChange={(v) => changeTier((v ?? "all") as TabValue)}>
            <TabsList>
              <TabsIndicator />
              {TABS.map((t) => (
                <TabsTrigger key={t.value} value={t.value}>
                  {t.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </div>
      </section>

      <section className="px-6 py-6">
        {tenantsQuery.isLoading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 9 }).map((_, i) => (
              <Skeleton key={i} variant="card" />
            ))}
          </div>
        ) : tenantsQuery.error ? (
          <ErrorInline
            message="Could not load tenants."
            onRetry={() => tenantsQuery.refetch()}
          />
        ) : items.length === 0 ? (
          <EmptyState
            title="No tenants match your filter"
            body="Try a different search or filter."
          />
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <AnimatePresence initial={false}>
              {items.map((t) => (
                <TenantCard key={t.id} tenant={t} onSelect={() => openTenant(t.id)} />
              ))}
            </AnimatePresence>
          </div>
        )}
      </section>

      <TenantDetailDrawer
        tenantId={selectedId}
        open={!!selectedId}
        onOpenChange={(o) => {
          if (!o) closeDrawer();
        }}
      />

    </div>
  );
}

export default function TenantsPage() {
  return (
    <Suspense fallback={null}>
      <TenantsPageInner />
    </Suspense>
  );
}
