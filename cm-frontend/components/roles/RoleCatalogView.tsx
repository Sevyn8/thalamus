"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Crown, Lock, User } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { ActionChip, ScopeChip } from "@/components/shared/Chips";
import { comingInV1 } from "@/components/shared/ComingInV1Toast";
import { EditRoleModal } from "@/components/roles/EditRoleModal";
import { useRoles, useRolePermissions } from "@/lib/hooks/use-roles";
import { useLookups } from "@/lib/hooks/use-lookups";
import { useCanDo } from "@/lib/auth/use-me-can-do";
import { cn } from "@/lib/utils";
import type { RoleListItem } from "@/types/api";

// Consumes backend's pre-grouped RoleListResponse
// {platform_roles, tenant_roles}. TENANT personas see platform_roles
// always empty per backend's audience filter; the Platform section is
// hidden entirely (not rendered as empty-state) to suppress an
// always-empty platform_roles block for TENANT.

type RoleCatalogProps = {
  selectedId: string | null;
  onSelect: (id: string) => void;
};

function RoleListGroup({
  label,
  count,
  roles,
  icon: Icon,
  selectedId,
  onSelect,
}: {
  label: string;
  count: number;
  roles: RoleListItem[];
  icon: React.ComponentType<{ className?: string }>;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (roles.length === 0) return null;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline gap-1.5 px-2 pt-3 text-label text-muted-foreground">
        <span>{label}</span>
        <span className="font-normal text-foreground-subtle">({count})</span>
      </div>
      <ul className="flex flex-col gap-0.5">
        {roles.map((r) => {
          const selected = r.id === selectedId;
          return (
            <li key={r.id}>
              <button
                type="button"
                onClick={() => onSelect(r.id)}
                aria-pressed={selected}
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-2 py-2 text-left transition-colors",
                  selected ? "bg-accent text-foreground" : "text-foreground/80 hover:bg-accent/40",
                )}
              >
                <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="flex items-center gap-1.5 truncate text-sm font-medium">
                    {r.name}
                    {r.is_system ? (
                      <Lock
                        className="h-3 w-3 text-muted-foreground"
                        aria-label="System role (not deletable)"
                      />
                    ) : null}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {r.user_count.toLocaleString()} {r.user_count === 1 ? "user" : "users"}
                  </span>
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function RoleCatalogView({ selectedId, onSelect }: RoleCatalogProps) {
  const rolesQuery = useRoles();
  const lookupsQuery = useLookups();
  const [editOpen, setEditOpen] = useState(false);

  // Role edit gates on ADMIN.ROLES.OVERRIDE.GLOBAL, PLATFORM-only by
  // construction. 4-arg useCanDo — no anchor for GLOBAL scope.
  const canEditRole = useCanDo("ADMIN", "ROLES", "OVERRIDE", "GLOBAL");
  const canEdit = canEditRole.data?.allowed !== false;

  const platformItems = rolesQuery.data?.platform_roles.items ?? [];
  const tenantItems = rolesQuery.data?.tenant_roles.items ?? [];
  const flatItems = [...platformItems, ...tenantItems];

  const effectiveSelectedId = selectedId ?? flatItems[0]?.id ?? null;
  const detailQuery = useRolePermissions(effectiveSelectedId ?? "");
  const detail = detailQuery.data;
  const detailRole = flatItems.find((r) => r.id === effectiveSelectedId) ?? null;
  const detailAudience = platformItems.some((r) => r.id === effectiveSelectedId)
    ? "PLATFORM"
    : "TENANT";

  function onEditClick() {
    if (!effectiveSelectedId) return;
    if (canEditRole.data?.allowed === false) {
      toast.error("You don't have permission to edit roles.");
      return;
    }
    setEditOpen(true);
  }

  const moduleLabel = (code: string) =>
    lookupsQuery.data?.modules.find((m) => m.code === code)?.display_name ?? code;
  const resourceLabel = (resource: string) =>
    // /permissions endpoint doesn't ship resource_label (E6 matrix
    // does, but not here). Fall back to the raw enum code if no
    // lookup row exists.
    lookupsQuery.data?.modules.find((m) => m.code === resource)?.display_name ??
    resource;

  const deleteDisabled = !!detailRole && (detailRole.is_system || detailRole.user_count > 0);
  const deleteReason = detailRole
    ? detailRole.is_system
      ? "Built-in roles cannot be deleted."
      : "Role has users assigned."
    : "";

  return (
    <div className="grid grid-cols-1 gap-6 px-6 py-6 lg:grid-cols-[280px_1fr]">
      <aside className="flex h-fit flex-col gap-2 rounded-md border border-border bg-card/30 p-4">
        {rolesQuery.isLoading ? (
          <Skeleton variant="row" count={10} />
        ) : rolesQuery.error ? (
          <ErrorInline message="Could not load roles." onRetry={() => rolesQuery.refetch()} />
        ) : (
          <>
            <RoleListGroup
              label="Platform roles"
              count={platformItems.length}
              roles={platformItems}
              icon={Crown}
              selectedId={effectiveSelectedId}
              onSelect={onSelect}
            />
            <RoleListGroup
              label="Tenant roles"
              count={tenantItems.length}
              roles={tenantItems}
              icon={User}
              selectedId={effectiveSelectedId}
              onSelect={onSelect}
            />
          </>
        )}
      </aside>

      <section className="flex flex-col gap-4">
        {detailQuery.isLoading ? (
          <div className="flex flex-col gap-3">
            <Skeleton variant="rect" />
            <Skeleton variant="row" count={6} />
          </div>
        ) : detailQuery.error ? (
          <ErrorInline message="Could not load role detail." onRetry={() => detailQuery.refetch()} />
        ) : !detail || !detailRole ? null : (
          <>
            <header className="flex flex-col gap-2 border-b border-border pb-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-col gap-1">
                  <Badge variant="outline" className="w-fit text-[10px] uppercase tracking-wide">
                    {detailAudience === "PLATFORM" ? "Platform role" : "Tenant role"}
                  </Badge>
                  <h2 className="text-heading">{detail.role_name}</h2>
                  <p className="max-w-xl text-sm text-muted-foreground">
                    {detailRole.description}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {detailRole.user_count.toLocaleString()}{" "}
                    {detailRole.user_count === 1 ? "user" : "users"} assigned
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    onClick={onEditClick}
                    disabled={!canEdit}
                    title={!canEdit ? "You don't have permission to edit roles." : undefined}
                  >
                    Edit
                  </Button>
                  <Button
                    variant="destructive"
                    disabled={deleteDisabled}
                    title={deleteDisabled ? deleteReason : undefined}
                    onClick={() => comingInV1("Delete role")}
                  >
                    Delete
                  </Button>
                </div>
              </div>
            </header>

            <div className="flex flex-col gap-2">
              <div className="text-label text-muted-foreground">
                Permissions ({detail.items.length})
              </div>
              {detail.items.length === 0 ? (
                <span className="text-sm text-muted-foreground">No permissions granted.</span>
              ) : (
                <ul className="divide-y divide-border rounded-md border border-border">
                  {detail.items.map((p) => (
                    <li
                      key={p.id}
                      className="flex flex-wrap items-center justify-between gap-3 px-3 py-2 text-sm"
                    >
                      <span className="min-w-0 flex-1 truncate">
                        <span className="text-muted-foreground">{moduleLabel(p.module)}</span>
                        <span className="text-muted-foreground"> &gt; </span>
                        <span className="font-medium">{resourceLabel(p.resource)}</span>
                      </span>
                      <span className="flex items-center gap-2">
                        <ActionChip action={p.action} />
                        <ScopeChip scope={p.scope} />
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </>
        )}
      </section>

      {effectiveSelectedId ? (
        <EditRoleModal
          open={editOpen}
          onOpenChange={setEditOpen}
          roleId={effectiveSelectedId}
        />
      ) : null}
    </div>
  );
}

// Disable-with-tooltip wrapper for the page-level "+ Custom role"
// button. Per integration plan §10.1: backend has no write surface
// in v0; keeping the button live with no backend support is
// misleading. Tooltip explains "post-v0" disposition.
export function CustomRoleButton() {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span tabIndex={0} className="inline-flex">
            <Button disabled aria-disabled="true">
              + Custom role
            </Button>
          </span>
        }
      />
      <TooltipContent>Custom role creation is post-v0.</TooltipContent>
    </Tooltip>
  );
}
