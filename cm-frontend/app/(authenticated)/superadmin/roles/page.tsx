"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/shared/PageHeader";
import { Tabs, TabsIndicator, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  CustomRoleButton,
  RoleCatalogView,
} from "@/components/roles/RoleCatalogView";
import { PermissionMatrixView } from "@/components/roles/PermissionMatrixView";
import { RoleAssignmentsView } from "@/components/roles/RoleAssignmentsView";

type TabValue = "catalog" | "matrix" | "assignments";

function isTab(v: string | null): v is TabValue {
  return v === "catalog" || v === "matrix" || v === "assignments";
}

function RolesPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const rawTab = searchParams.get("tab");
  const tab: TabValue = isTab(rawTab) ? rawTab : "catalog";
  const roleId = searchParams.get("role");

  function changeTab(next: TabValue) {
    const sp = new URLSearchParams(searchParams.toString());
    if (next === "catalog") sp.delete("tab");
    else sp.set("tab", next);
    const qs = sp.toString();
    router.replace(`/superadmin/roles${qs ? `?${qs}` : ""}`);
  }

  function selectRole(id: string) {
    const sp = new URLSearchParams(searchParams.toString());
    sp.set("role", id);
    const qs = sp.toString();
    router.replace(`/superadmin/roles${qs ? `?${qs}` : ""}`);
  }

  return (
    <div className="flex flex-col">
      <PageHeader
        title="Roles & Permissions"
        subtitle="Permission = Module + Resource + Action + Scope"
        rightSlot={<CustomRoleButton />}
      />

      <div className="px-6 pt-6">
        <Tabs value={tab} onValueChange={(v) => changeTab((v ?? "catalog") as TabValue)}>
          <TabsList>
              <TabsIndicator />
            <TabsTrigger value="catalog">Role catalog</TabsTrigger>
            <TabsTrigger value="matrix">Permission matrix</TabsTrigger>
            <TabsTrigger value="assignments">Role assignments</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {tab === "catalog" ? (
        <RoleCatalogView selectedId={roleId} onSelect={selectRole} />
      ) : tab === "matrix" ? (
        <PermissionMatrixView />
      ) : (
        <RoleAssignmentsView />
      )}
    </div>
  );
}

export default function RolesPage() {
  return (
    <Suspense fallback={null}>
      <RolesPageInner />
    </Suspense>
  );
}
