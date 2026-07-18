"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Search, Store as StoreIcon } from "lucide-react";
import { toast } from "sonner";

import { useCanDo } from "@/lib/auth/use-me-can-do";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { hasPermission } from "@/lib/auth/permissions-check";
import { PageHeader } from "@/components/shared/PageHeader";
import { Input } from "@/components/ui/input";
import { Tabs, TabsIndicator, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { EmptyState } from "@/components/shared/EmptyState";
import { StoreCard } from "@/components/stores/StoreCard";
import { StoreDetailDrawer } from "@/components/stores/StoreDetailDrawer";
import { CreateStoreModal } from "@/components/stores/CreateStoreModal";
import { useStores } from "@/lib/hooks/use-stores";
import { useTenants } from "@/lib/hooks/use-tenants";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { cn } from "@/lib/utils";
import type { StoreStatus } from "@/types/api";

type TabValue = "all" | StoreStatus;

const TABS: { value: TabValue; label: string }[] = [
  { value: "all", label: "All" },
  { value: "OPENING", label: "Opening" },
  { value: "ACTIVE", label: "Active" },
  { value: "INACTIVE", label: "Inactive" },
  { value: "CLOSED", label: "Closed" },
];

const STATUS_VALUES: StoreStatus[] = ["OPENING", "ACTIVE", "INACTIVE", "CLOSED"];

function isStoreStatus(v: string | null): v is StoreStatus {
  return v !== null && (STATUS_VALUES as string[]).includes(v);
}

function StoresPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const snapshot = useAuthSnapshot();

  const urlSearch = searchParams.get("search") ?? "";
  const urlStatus = searchParams.get("status");
  const urlTab: TabValue = isStoreStatus(urlStatus) ? urlStatus : "all";
  const urlTenantId = searchParams.get("tenant_id") ?? "";
  const selectedId = searchParams.get("store");

  const [search, setSearch] = useState(urlSearch);
  const debouncedSearch = useDebouncedValue(search, 300);
  const [createOpen, setCreateOpen] = useState(false);

  // Phase 5g.1.4: PLATFORM-only tenant filter. Backend's
  // GET /api/v1/stores accepts tenant_id; TENANT-OWNER doesn't see
  // the dropdown (their list is RLS-scoped to their own tenant, so
  // the filter is meaningless).
  const canListAllTenants = hasPermission(
    snapshot,
    "ADMIN",
    "TENANTS",
    "VIEW",
    "GLOBAL",
  );
  const tenantsQuery = useTenants(undefined, { enabled: canListAllTenants });
  const tenants = tenantsQuery.data?.items ?? [];

  // Single permission tuple covers all Stores write operations
  // (create, patch, set-status) per the backend's LD9: CONFIGURE.TENANT
  // gates everything. PLATFORM passes via GLOBAL→TENANT cascade.
  const canConfigureStores = useCanDo(
    "ADMIN",
    "STORES",
    "CONFIGURE",
    "TENANT",
  );

  function onAddStoreClick() {
    if (canConfigureStores.data?.allowed === false) {
      toast.error("You don't have permission to add stores.");
      return;
    }
    setCreateOpen(true);
  }

  useEffect(() => {
    if (debouncedSearch === urlSearch) return;
    const sp = new URLSearchParams(searchParams.toString());
    if (debouncedSearch) sp.set("search", debouncedSearch);
    else sp.delete("search");
    const qs = sp.toString();
    router.replace(`/superadmin/stores${qs ? `?${qs}` : ""}`);
  }, [debouncedSearch, urlSearch, searchParams, router]);

  function changeStatus(next: TabValue) {
    const sp = new URLSearchParams(searchParams.toString());
    if (next === "all") sp.delete("status");
    else sp.set("status", next);
    const qs = sp.toString();
    router.replace(`/superadmin/stores${qs ? `?${qs}` : ""}`);
  }

  function changeTenantFilter(value: string) {
    const sp = new URLSearchParams(searchParams.toString());
    if (value) sp.set("tenant_id", value);
    else sp.delete("tenant_id");
    const qs = sp.toString();
    router.replace(`/superadmin/stores${qs ? `?${qs}` : ""}`);
  }

  function openStore(id: string) {
    const sp = new URLSearchParams(searchParams.toString());
    sp.set("store", id);
    router.push(`/superadmin/stores?${sp.toString()}`);
  }

  function closeDrawer() {
    const sp = new URLSearchParams(searchParams.toString());
    sp.delete("store");
    const qs = sp.toString();
    router.replace(`/superadmin/stores${qs ? `?${qs}` : ""}`);
  }

  const storesQuery = useStores({
    status: urlTab !== "all" ? urlTab : undefined,
    search: debouncedSearch || undefined,
    tenant_id: urlTenantId || undefined,
  });
  const items = storesQuery.data?.items ?? [];
  const totalUnfiltered =
    !debouncedSearch && urlTab === "all"
      ? storesQuery.data?.pagination?.total ?? 0
      : null;

  const subtitle = storesQuery.data
    ? `${storesQuery.data.pagination.total.toLocaleString()} stores`
    : "Loading...";

  return (
    <div className="flex flex-col">
      <PageHeader
        title="Stores"
        subtitle={subtitle}
        primaryAction={{
          label: "+ Add Store",
          onClick: onAddStoreClick,
        }}
      />

      <section className="flex flex-col gap-4 px-6 pt-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-1 flex-col gap-3 sm:flex-row sm:items-center">
            <div className="relative w-full max-w-sm">
              <Search
                className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                type="search"
                placeholder="Search stores..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-8"
              />
            </div>
            {canListAllTenants ? (
              <select
                aria-label="Filter by tenant"
                value={urlTenantId}
                onChange={(e) => changeTenantFilter(e.target.value)}
                className={cn(
                  "h-8 min-w-[200px] rounded-md border border-input bg-background px-2.5 py-1 text-sm",
                  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
                  "dark:bg-input/30",
                )}
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
          <Tabs value={urlTab} onValueChange={(v) => changeStatus((v ?? "all") as TabValue)}>
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
        {storesQuery.isLoading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} variant="card" />
            ))}
          </div>
        ) : storesQuery.error ? (
          <ErrorInline
            message="Could not load stores."
            onRetry={() => storesQuery.refetch()}
          />
        ) : totalUnfiltered === 0 ? (
          <EmptyState
            icon={<StoreIcon />}
            title="No stores yet"
            body="Add your first store to get started."
            action={
              canConfigureStores.data?.allowed !== false
                ? { label: "Add Store", onClick: onAddStoreClick }
                : undefined
            }
          />
        ) : items.length === 0 ? (
          <EmptyState
            title="No stores match your filter"
            body="Try a different search or status."
          />
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((s) => (
              <StoreCard key={s.id} store={s} onSelect={() => openStore(s.id)} />
            ))}
          </div>
        )}
      </section>

      <StoreDetailDrawer
        storeId={selectedId}
        open={!!selectedId}
        onOpenChange={(o) => {
          if (!o) closeDrawer();
        }}
      />

      <CreateStoreModal
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(id) => openStore(id)}
      />
    </div>
  );
}

export default function StoresPage() {
  return (
    <Suspense fallback={null}>
      <StoresPageInner />
    </Suspense>
  );
}
