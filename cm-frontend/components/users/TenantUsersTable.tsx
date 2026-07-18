"use client";

import { MoreVertical } from "lucide-react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { StatusChip } from "@/components/shared/Chips";
import { initials, avatarTone } from "@/lib/utils/initials";
import { formatUserRoles } from "@/lib/format/user-roles";
import { cn } from "@/lib/utils";
import type { TenantUser } from "@/types/api";

type TenantUsersTableProps = {
  users: TenantUser[];
  // Map of tenant id → display name. Backend's TenantUserRead carries
  // only tenant_id; the page resolves names from `useTenants()` and
  // hands the lookup down. Missing entries fall through to "—".
  tenantNamesById: Map<string, string>;
  selectedId: string | null;
  onSelect: (id: string) => void;
};

export function TenantUsersTable({
  users,
  tenantNamesById,
  selectedId,
  onSelect,
}: TenantUsersTableProps) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="px-3 text-label text-muted-foreground">User</TableHead>
          <TableHead className="text-label text-muted-foreground">Tenant</TableHead>
          <TableHead className="text-label text-muted-foreground">Roles</TableHead>
          <TableHead className="text-label text-muted-foreground">Status</TableHead>
          <TableHead className="w-8" aria-label="Row actions" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {users.map((u) => {
          const isSelected = u.id === selectedId;
          return (
            <TableRow
              key={u.id}
              data-state={isSelected ? "selected" : undefined}
              onClick={() => onSelect(u.id)}
              className="cursor-pointer"
            >
              <TableCell className="px-3 py-3">
                <div className="flex items-center gap-3">
                  <span
                    className={cn(
                      "flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-xs font-semibold",
                      avatarTone(u.full_name),
                    )}
                    aria-hidden="true"
                  >
                    {initials(u.full_name)}
                  </span>
                  <div className="flex min-w-0 flex-col">
                    <span className="truncate text-sm font-medium">{u.full_name}</span>
                    <span className="truncate text-xs text-muted-foreground">
                      {u.email}
                    </span>
                  </div>
                </div>
              </TableCell>
              <TableCell className="text-sm">
                {tenantNamesById.get(u.tenant_id) ?? "—"}
              </TableCell>
              <TableCell className="text-sm text-foreground-muted">
                {formatUserRoles(u.roles)}
              </TableCell>
              <TableCell>
                <StatusChip status={u.status} />
              </TableCell>
              <TableCell className="w-8 px-2">
                <button
                  type="button"
                  aria-label="User actions"
                  onClick={(e) => e.stopPropagation()}
                  className="invisible rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                  <MoreVertical className="h-4 w-4" />
                </button>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
