"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Search } from "lucide-react";

import { PageHeader } from "@/components/shared/PageHeader";
import { Input } from "@/components/ui/input";
import { Tabs, TabsIndicator, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { EmptyState } from "@/components/shared/EmptyState";
import { PlatformUsersTable } from "@/components/users/PlatformUsersTable";
import { TenantUsersTable } from "@/components/users/TenantUsersTable";
import { PlatformUserDetailDrawer } from "@/components/users/PlatformUserDetailDrawer";
import { TenantUserDetailDrawer } from "@/components/users/TenantUserDetailDrawer";
import { CreateTenantUserModal } from "@/components/users/CreateTenantUserModal";
import { usePlatformUsers } from "@/lib/hooks/use-platform-users";
import { useTenantUsers } from "@/lib/hooks/use-tenant-users";
import { useTenants } from "@/lib/hooks/use-tenants";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { useCanDo } from "@/lib/auth/use-me-can-do";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { hasPermission } from "@/lib/auth/permissions-check";
import { cn } from "@/lib/utils";

type Audience = "platform" | "tenant";

const AUDIENCE_VALUES: Audience[] = ["platform", "tenant"];

function isAudience(v: string | null): v is Audience {
  return v !== null && (AUDIENCE_VALUES as string[]).includes(v);
}

function UsersPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const snapshot = useAuthSnapshot();

  // Per-tab visibility on backend grants. Platform tab requires
  // ADMIN.USERS.VIEW.GLOBAL (cross-tenant); Tenant tab needs
  // ADMIN.USERS.VIEW.TENANT (own-tenant) or GLOBAL (cascade). Each
  // gate fail-closes during boot, then resolves once the snapshot
  // populates. TENANT-OWNER sees Tenant tab only; PLATFORM sees both.
  const canViewPlatformUsers = hasPermission(
    snapshot,
    "ADMIN",
    "USERS",
    "VIEW",
    "GLOBAL",
  );
  const canViewTenantUsers =
    hasPermission(snapshot, "ADMIN", "USERS", "VIEW", "TENANT") ||
    canViewPlatformUsers;

  const rawAudience = searchParams.get("audience");
  const requestedAudience: Audience = isAudience(rawAudience)
    ? (rawAudience as Audience)
    : "platform";
  // Default fallback: if the requested audience isn't visible to this
  // persona, route to the one that is. Platform-first when both
  // visible (matches PLATFORM-persona muscle memory); Tenant-only
  // when Platform is gated out.
  const audience: Audience =
    requestedAudience === "platform" && !canViewPlatformUsers
      ? "tenant"
      : requestedAudience === "tenant" && !canViewTenantUsers
        ? "platform"
        : requestedAudience;

  const urlSearch = searchParams.get("search") ?? "";
  const urlTenantId = searchParams.get("tenant_id") ?? "";
  const selectedUserId = searchParams.get("user");

  const [search, setSearch] = useState(urlSearch);
  const debouncedSearch = useDebouncedValue(search, 300);
  const [createOpen, setCreateOpen] = useState(false);

  // Tenant-create gate is unanchored at the page level — we don't yet
  // know which tenant the operator will pick inside the modal. PLATFORM
  // passes via the cascade; TENANT-OWNER's per-tenant grant lets the
  // backend make the real call when POST fires. Same tuple as the
  // four tenant-user writes (multi-audience).
  const canInviteTenantUser = useCanDo(
    "ADMIN",
    "USERS",
    "CONFIGURE",
    "TENANT",
  );
  const showInviteButton =
    canInviteTenantUser.data?.allowed !== false;

  useEffect(() => {
    if (debouncedSearch === urlSearch) return;
    const sp = new URLSearchParams(searchParams.toString());
    if (debouncedSearch) sp.set("search", debouncedSearch);
    else sp.delete("search");
    const qs = sp.toString();
    router.replace(`/superadmin/users${qs ? `?${qs}` : ""}`);
  }, [debouncedSearch, urlSearch, searchParams, router]);

  function changeAudience(next: Audience) {
    const sp = new URLSearchParams(searchParams.toString());
    sp.set("audience", next);
    // The tenant-id filter only applies to the Tenant tab; clear it
    // when switching to Platform so a stale filter doesn't carry over.
    if (next === "platform") sp.delete("tenant_id");
    sp.delete("user");
    const qs = sp.toString();
    router.replace(`/superadmin/users${qs ? `?${qs}` : ""}`);
  }

  function changeTenantFilter(value: string) {
    const sp = new URLSearchParams(searchParams.toString());
    if (value) sp.set("tenant_id", value);
    else sp.delete("tenant_id");
    const qs = sp.toString();
    router.replace(`/superadmin/users${qs ? `?${qs}` : ""}`);
  }

  function selectUser(id: string) {
    const sp = new URLSearchParams(searchParams.toString());
    sp.set("user", id);
    router.push(`/superadmin/users?${sp.toString()}`);
  }

  function closeDrawer() {
    const sp = new URLSearchParams(searchParams.toString());
    sp.delete("user");
    const qs = sp.toString();
    router.replace(`/superadmin/users${qs ? `?${qs}` : ""}`);
  }

  // Tenants list — populates the Tenant tab's filter dropdown and
  // resolves tenant_id → name for the Tenant table. Backend's
  // GET /api/v1/tenants requires ADMIN.TENANTS.VIEW.GLOBAL — gated for
  // TENANT-OWNER personas (they implicitly see only their own tenant
  // via RLS, so the filter is meaningless to them anyway).
  const canListAllTenants = hasPermission(
    snapshot,
    "ADMIN",
    "TENANTS",
    "VIEW",
    "GLOBAL",
  );
  const tenantsQuery = useTenants(undefined, { enabled: canListAllTenants });
  const tenantsItems = tenantsQuery.data?.items;
  const tenants = useMemo(() => tenantsItems ?? [], [tenantsItems]);
  const tenantNamesById = useMemo(() => {
    const m = new Map<string, string>();
    for (const t of tenants) m.set(t.id, t.name);
    return m;
  }, [tenants]);

  // Both queries are always wired so switching tabs is instant
  // (TanStack Query caches the off-screen tab's data). Inactive tab
  // data isn't displayed but the network calls fire on mount only.
  const platformQuery = usePlatformUsers(
    { search: debouncedSearch || undefined },
    { enabled: canViewPlatformUsers },
  );
  const tenantQuery = useTenantUsers({
    search: debouncedSearch || undefined,
    tenant_id: urlTenantId || undefined,
  });

  const activeQuery = audience === "platform" ? platformQuery : tenantQuery;
  const items = activeQuery.data?.items ?? [];
  const total = activeQuery.data?.pagination.total ?? 0;

  const audienceLabel = audience === "platform" ? "platform user" : "tenant user";
  const subtitle = activeQuery.isLoading
    ? "Loading..."
    : `${total.toLocaleString()} ${audienceLabel}${total === 1 ? "" : "s"} visible`;

  return (
    <div className="flex flex-col">
      <PageHeader
        title="Users"
        subtitle={subtitle}
        primaryAction={
          audience === "tenant" && showInviteButton
            ? { label: "+ Invite user", onClick: () => setCreateOpen(true) }
            : undefined
        }
      />

      <section className="flex flex-col gap-4 px-6 pt-6">
        {canViewPlatformUsers && canViewTenantUsers ? (
          <Tabs
            value={audience}
            onValueChange={(v) => changeAudience((v ?? "platform") as Audience)}
          >
            <TabsList>
              <TabsIndicator />
              <TabsTrigger value="platform">Platform</TabsTrigger>
              <TabsTrigger value="tenant">Tenant</TabsTrigger>
            </TabsList>
          </Tabs>
        ) : null}

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="relative w-full max-w-sm">
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              type="search"
              placeholder="Search by name or email..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8"
            />
          </div>
          {audience === "tenant" && canListAllTenants ? (
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
      </section>

      <section className="px-6 py-6">
        {activeQuery.isLoading ? (
          <Skeleton variant="row" count={10} />
        ) : activeQuery.error ? (
          <ErrorInline
            message="Could not load users."
            onRetry={() => activeQuery.refetch()}
          />
        ) : items.length === 0 ? (
          <EmptyState
            title="No users match your filter"
            body="Try a different search or tenant."
          />
        ) : audience === "platform" ? (
          <PlatformUsersTable
            users={platformQuery.data?.items ?? []}
            selectedId={selectedUserId}
            onSelect={selectUser}
          />
        ) : (
          <TenantUsersTable
            users={tenantQuery.data?.items ?? []}
            tenantNamesById={tenantNamesById}
            selectedId={selectedUserId}
            onSelect={selectUser}
          />
        )}
      </section>

      <PlatformUserDetailDrawer
        userId={audience === "platform" ? selectedUserId : null}
        open={audience === "platform" && !!selectedUserId}
        onOpenChange={(o) => {
          if (!o) closeDrawer();
        }}
      />
      <TenantUserDetailDrawer
        userId={audience === "tenant" ? selectedUserId : null}
        open={audience === "tenant" && !!selectedUserId}
        onOpenChange={(o) => {
          if (!o) closeDrawer();
        }}
      />

      <CreateTenantUserModal
        open={createOpen}
        onOpenChange={setCreateOpen}
        // TENANT-OWNER persona has exactly one tenant — auto-bind from
        // JWT claims so the modal hides the picker. PLATFORM falls back
        // to the URL tenant filter (if set) or shows the picker
        // (preselected=undefined).
        preselectedTenantId={
          snapshot?.user?.userType === "TENANT"
            ? snapshot.user.tenantId ?? undefined
            : urlTenantId || undefined
        }
      />
    </div>
  );
}

export default function UsersPage() {
  return (
    <Suspense fallback={null}>
      <UsersPageInner />
    </Suspense>
  );
}
