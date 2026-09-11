"use client";

import { useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { EmptyState } from "@/components/shared/EmptyState";
import { Chip, type Tone } from "@/components/shared/Chips";
import { OrgNodeTypeBadge } from "@/components/org/OrgNodeTypeBadge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useRoleAssignments, useRoles } from "@/lib/hooks/use-roles";
import { useTenants } from "@/lib/hooks/use-tenants";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import type { RoleAssignmentsParams } from "@/lib/api/roles";
import type {
  OrgNodeType,
  PlatformAssignmentItem,
  TenantAssignmentItem,
} from "@/types/api";
import { cn } from "@/lib/utils";

// Role Assignments tab on /superadmin/roles.
//
// Server-side RLS scopes for TENANT JWTs (Kowalski sees 0 platform
// assignments + 4 Żabka tenant assignments). PLATFORM JWTs see the
// fleet (3 platform + 19 tenant). UI hides the PLATFORM block for
// TENANT personas entirely — matches the launcher's hide-vs-Coming-
// Soon philosophy.
//
// Org-node-level scoping: tenant assignments are scoped at org-node
// level (HQ/region/store), NOT just tenant. Same user can hold OWNER
// at the tenant root AND STORE_MANAGER at a specific store. The
// org_node column is load-bearing; without it the rows would read
// as duplicate/contradictory.

type Audience = "platform" | "tenant" | "both";

// Backend's openapi types `status` as plain string (not the
// UserRoleAssignmentStatus enum reference). Lookup is Record<string,
// Tone> with a grey fallback for any future status value that
// surfaces before the frontend recipe is updated.
const STATUS_TONE: Record<string, Tone> = {
  ACTIVE: "green",
  INACTIVE: "grey",
};

function toneFor(status: string): Tone {
  return STATUS_TONE[status] ?? "grey";
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return iso.slice(0, 10);
}

function PlatformAssignmentRow({ item }: { item: PlatformAssignmentItem }) {
  return (
    <TableRow>
      <TableCell>
        <div className="flex flex-col gap-0.5">
          <span className="text-body-strong">{item.platform_user.full_name}</span>
          <span className="text-caption text-foreground-muted">
            {item.platform_user.email}
          </span>
        </div>
      </TableCell>
      <TableCell>
        <span className="font-mono text-caption">{item.role.code}</span>
        <span className="ml-2 text-caption text-foreground-muted">
          {item.role.name}
        </span>
      </TableCell>
      <TableCell className="text-caption">
        {formatDate(item.granted_at)}
      </TableCell>
      <TableCell>
        <Chip tone={toneFor(item.status)}>{item.status}</Chip>
      </TableCell>
    </TableRow>
  );
}

function TenantAssignmentRow({
  item,
  isPlatform,
}: {
  item: TenantAssignmentItem;
  isPlatform: boolean;
}) {
  return (
    <TableRow>
      <TableCell>
        <div className="flex flex-col gap-0.5">
          <span className="text-body-strong">{item.tenant_user.full_name}</span>
          <span className="text-caption text-foreground-muted">
            {item.tenant_user.email}
          </span>
        </div>
      </TableCell>
      {isPlatform ? (
        <TableCell className="text-body-strong">{item.tenant.name}</TableCell>
      ) : null}
      <TableCell>
        <div className="flex items-center gap-2">
          <span>{item.org_node.name}</span>
          <OrgNodeTypeBadge type={item.org_node.node_type as OrgNodeType} />
        </div>
      </TableCell>
      <TableCell>
        <span className="font-mono text-caption">{item.role.code}</span>
        <span className="ml-2 text-caption text-foreground-muted">
          {item.role.name}
        </span>
      </TableCell>
      <TableCell className="text-caption">
        {formatDate(item.granted_at)}
      </TableCell>
      <TableCell>
        <Chip tone={toneFor(item.status)}>{item.status}</Chip>
      </TableCell>
    </TableRow>
  );
}

export function RoleAssignmentsView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const snapshot = useAuthSnapshot();
  const isPlatform = snapshot?.user.userType === "PLATFORM";

  // URL-param filter state. role_id + tenant_id are exposed in the
  // filter bar; the other 4 backend filters (platform_user_id /
  // tenant_user_id / org_node_id / status) remain deep-linkable via
  // URL but have no in-page UI in v1.
  const urlRoleId = searchParams.get("role_id") ?? "";
  const urlTenantId = searchParams.get("tenant_id") ?? "";
  const urlAudience: Audience = isPlatform
    ? (searchParams.get("audience") as Audience) ?? "both"
    : "tenant";

  const params = useMemo<RoleAssignmentsParams>(() => {
    const p: RoleAssignmentsParams = {};
    if (urlRoleId) p.role_id = urlRoleId;
    if (urlTenantId && isPlatform) p.tenant_id = urlTenantId;
    return p;
  }, [urlRoleId, urlTenantId, isPlatform]);

  const assignments = useRoleAssignments(params);
  const rolesQuery = useRoles();
  const tenantsQuery = useTenants({ limit: 50 });

  function changeFilter(key: string, value: string) {
    const sp = new URLSearchParams(searchParams.toString());
    if (value) sp.set(key, value);
    else sp.delete(key);
    const qs = sp.toString();
    router.replace(`/superadmin/roles${qs ? `?${qs}` : ""}`);
  }

  const platformItems = assignments.data?.platform_assignments.items ?? [];
  const tenantItems = assignments.data?.tenant_assignments.items ?? [];

  const showPlatformBlock =
    isPlatform && (urlAudience === "platform" || urlAudience === "both");
  const showTenantBlock =
    !isPlatform || urlAudience === "tenant" || urlAudience === "both";

  return (
    <div className="flex flex-col gap-6 px-6 py-6">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex flex-col gap-1 text-caption text-foreground-muted">
          Role
          <select
            value={urlRoleId}
            onChange={(e) => changeFilter("role_id", e.target.value)}
            className="h-8 min-w-[200px] rounded-md border border-input bg-background px-2.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 dark:bg-input/30"
          >
            <option value="">All roles</option>
            {(rolesQuery.data?.platform_roles.items ?? [])
              .concat(rolesQuery.data?.tenant_roles.items ?? [])
              .map((r) => (
                <option key={r.id} value={r.id}>
                  {r.code} — {r.name}
                </option>
              ))}
          </select>
        </label>

        {isPlatform ? (
          <label className="flex flex-col gap-1 text-caption text-foreground-muted">
            Tenant
            <select
              value={urlTenantId}
              onChange={(e) => changeFilter("tenant_id", e.target.value)}
              className="h-8 min-w-[200px] rounded-md border border-input bg-background px-2.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 dark:bg-input/30"
            >
              <option value="">All tenants</option>
              {(tenantsQuery.data?.items ?? []).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        {isPlatform ? (
          <fieldset className="flex items-end gap-3">
            <legend className="sr-only">Audience</legend>
            {(["both", "platform", "tenant"] as const).map((a) => (
              <label
                key={a}
                className={cn(
                  "flex cursor-pointer items-center gap-1.5 text-caption",
                  urlAudience === a
                    ? "text-foreground"
                    : "text-foreground-muted",
                )}
              >
                <input
                  type="radio"
                  name="audience"
                  value={a}
                  checked={urlAudience === a}
                  onChange={() =>
                    changeFilter("audience", a === "both" ? "" : a)
                  }
                />
                {a === "both" ? "Both" : a === "platform" ? "Platform" : "Tenant"}
              </label>
            ))}
          </fieldset>
        ) : null}
      </div>

      {assignments.isLoading ? (
        <div className="flex flex-col gap-4">
          <Skeleton variant="card" className="h-32 w-full" />
          <Skeleton variant="card" className="h-64 w-full" />
        </div>
      ) : assignments.error ? (
        <ErrorInline message="Could not load role assignments." />
      ) : (
        <>
          {showPlatformBlock ? (
            <section className="flex flex-col gap-3">
              <h2 className="text-heading">Platform assignments</h2>
              {platformItems.length === 0 ? (
                <EmptyState
                  title="No platform assignments"
                  body="No assignments match your filters."
                />
              ) : (
                <div className="overflow-x-auto rounded-md border border-border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>User</TableHead>
                        <TableHead>Role</TableHead>
                        <TableHead>Granted</TableHead>
                        <TableHead>Status</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {platformItems.map((item) => (
                        <PlatformAssignmentRow key={item.id} item={item} />
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </section>
          ) : null}

          {showTenantBlock ? (
            <section className="flex flex-col gap-3">
              <h2 className="text-heading">Tenant assignments</h2>
              {tenantItems.length === 0 ? (
                <EmptyState
                  title="No tenant assignments"
                  body="No assignments match your filters."
                />
              ) : (
                <div className="overflow-x-auto rounded-md border border-border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>User</TableHead>
                        {isPlatform ? <TableHead>Tenant</TableHead> : null}
                        <TableHead>Org node</TableHead>
                        <TableHead>Role</TableHead>
                        <TableHead>Granted</TableHead>
                        <TableHead>Status</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {tenantItems.map((item) => (
                        <TenantAssignmentRow
                          key={item.id}
                          item={item}
                          isPlatform={isPlatform}
                        />
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}
