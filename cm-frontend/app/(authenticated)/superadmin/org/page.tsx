"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/shared/PageHeader";
import { TenantList } from "@/components/org/TenantList";
import { OrgTreePane } from "@/components/org/OrgTree";
import { NodeDetailDrawer } from "@/components/org/NodeDetailDrawer";
import { useTenants } from "@/lib/hooks/use-tenants";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { hasPermission } from "@/lib/auth/permissions-check";
import { cn } from "@/lib/utils";
import type { OrgNodeTreeItem } from "@/types/api";

function OrgPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const snapshot = useAuthSnapshot();

  // Cross-tenant tenant picker requires ADMIN.TENANTS.VIEW.GLOBAL.
  // TENANT-OWNER personas (no GLOBAL grant) would hit a 403 on
  // `/api/v1/tenants` — which would surface as a "Could not load
  // tenants" error panel in the picker, blocking the whole surface —
  // even though they can only ever see their own tenant's tree anyway.
  // So the fetch is skipped for TENANT: their tenant is auto-selected
  // from JWT claims and the picker is hidden entirely (single-tenant
  // tree is full-width).
  const canListAllTenants = hasPermission(
    snapshot,
    "ADMIN",
    "TENANTS",
    "VIEW",
    "GLOBAL",
  );

  const tenantsQuery = useTenants(undefined, { enabled: canListAllTenants });
  const tenants = tenantsQuery.data?.items ?? [];

  const urlTenant = searchParams.get("tenant");
  // PLATFORM: URL → first fetched tenant → null
  // TENANT: persona's own tenant from JWT (no fetch needed)
  const selectedTenantId = canListAllTenants
    ? urlTenant ?? tenants[0]?.id ?? null
    : snapshot?.user?.tenantId ?? null;

  // Node selection is component-local state, not URL-driven: lazy-loaded
  // grandchildren live in TQ cache via useInfiniteQuery (not in
  // tree.data.tree), so a URL-driven findNode lookup couldn't resolve
  // them on a fresh page load. Click-driven selection passes the full
  // OrgNodeTreeItem object up; URL keeps only `?tenant=` for shareable
  // tenant links.
  const [selectedNode, setSelectedNode] = useState<OrgNodeTreeItem | null>(
    null,
  );

  function selectTenant(id: string) {
    if (id === selectedTenantId) return;
    setSelectedNode(null);
    const sp = new URLSearchParams(searchParams.toString());
    sp.set("tenant", id);
    router.replace(`/superadmin/org?${sp.toString()}`);
  }

  function selectNode(node: OrgNodeTreeItem) {
    setSelectedNode(node);
  }

  function closeDrawer() {
    setSelectedNode(null);
  }

  return (
    <div className="flex flex-col">
      <PageHeader
        title="Organization Tree"
        subtitle="Hierarchy: HQ → Region → Store → Department. Permissions cascade down."
      />

      <div
        className={cn(
          "grid grid-cols-1 gap-6 px-6 py-6",
          canListAllTenants && "lg:grid-cols-[280px_1fr]",
        )}
      >
        {canListAllTenants ? (
          <TenantList
            tenants={tenants}
            selectedId={selectedTenantId}
            onSelect={selectTenant}
            loading={tenantsQuery.isLoading}
            hasError={!!tenantsQuery.error}
            onRetry={() => tenantsQuery.refetch()}
          />
        ) : null}
        <OrgTreePane
          key={selectedTenantId ?? "none"}
          tenantId={selectedTenantId}
          selectedNodeId={selectedNode?.id ?? null}
          selectedNode={selectedNode}
          onNodeSelect={selectNode}
        />
      </div>

      <NodeDetailDrawer
        node={selectedNode}
        open={!!selectedNode}
        onOpenChange={(o) => {
          if (!o) closeDrawer();
        }}
      />
    </div>
  );
}

export default function OrgPage() {
  return (
    <Suspense fallback={null}>
      <OrgPageInner />
    </Suspense>
  );
}
