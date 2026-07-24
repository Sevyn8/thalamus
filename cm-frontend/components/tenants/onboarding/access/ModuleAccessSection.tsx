"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Lock } from "lucide-react";

import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { ApiError } from "@/lib/api/client";
import type { WritableModuleCode } from "@/lib/api/modules";
import { useCanDo } from "@/lib/auth/use-me-can-do";
import {
  useModuleCards,
  useEnableModuleAccess,
  useDisableModuleAccess,
} from "@/lib/hooks/use-modules";
import { useTenantModuleRow } from "@/lib/hooks/use-tenant-module-access";

// ADMIN is force-enabled at tenant create and underpins the admin surface;
// it renders as a locked row and is never sent to the toggle endpoints
// (the backend currently would accept disabling it — tracked as a backend
// follow-up).
const ADMIN_CODE = "ADMIN";

export function ModuleAccessSection({
  tenantId,
  tenantName,
}: {
  tenantId: string;
  tenantName?: string;
}) {
  const qc = useQueryClient();
  // Module toggles gate on ADMIN.TENANTS.OVERRIDE.GLOBAL (SUPER_ADMIN),
  // which is narrower than the wizard's CONFIGURE gate. Pre-check via
  // /me/can-do and offer switches ONLY when explicitly allowed, so a
  // switch is never presented that would 403 on click.
  const canDo = useCanDo("ADMIN", "TENANTS", "OVERRIDE", "GLOBAL");
  const canToggle = canDo.data?.allowed === true;

  const rowQuery = useTenantModuleRow(tenantId, tenantName);
  const cardsQuery = useModuleCards();
  const enable = useEnableModuleAccess();
  const disable = useDisableModuleAccess();
  const [pending, setPending] = useState<string | null>(null);

  const labelFor = (code: string): string =>
    cardsQuery.data?.items.find((c) => c.module_code === code)?.module_label ??
    code;

  async function onToggle(code: WritableModuleCode, next: boolean) {
    setPending(code);
    try {
      if (next) await enable.mutateAsync({ tenantId, moduleCode: code });
      else await disable.mutateAsync({ tenantId, moduleCode: code });
      void qc.invalidateQueries({ queryKey: ["tenant-module-row"] });
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        toast.error("You don't have permission to change module access.");
      } else {
        toast.error("Could not change module access. Please try again.");
      }
    } finally {
      setPending(null);
    }
  }

  if (rowQuery.isLoading) {
    return <Skeleton variant="card" />;
  }
  if (rowQuery.error) {
    return (
      <ErrorInline
        title="Could not load module access"
        message="The tenant's module row could not be resolved."
        onRetry={() => rowQuery.refetch()}
      />
    );
  }

  const cells = rowQuery.data?.cells ?? [];

  return (
    <div className="flex flex-col gap-3">
      {!canToggle ? (
        <p className="rounded-md border border-border bg-muted/30 p-2.5 text-xs text-muted-foreground">
          Module access is read-only: changing it requires the
          super-admin OVERRIDE permission.
        </p>
      ) : null}

      <ul className="flex flex-col divide-y divide-border rounded-md border border-border">
        {cells.map((cell) => {
          const isAdmin = cell.module_code === ADMIN_CODE;
          const enabled = cell.status === "ENABLED";
          const isPending = pending === cell.module_code;
          return (
            <li
              key={cell.module_code}
              className="flex items-center justify-between gap-3 px-4 py-3"
            >
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">
                  {labelFor(cell.module_code)}
                </span>
                {isAdmin ? (
                  <span
                    className="inline-flex items-center gap-1 text-xs text-muted-foreground"
                    title="The Admin module is always enabled and cannot be turned off."
                  >
                    <Lock className="h-3 w-3" /> Always on
                  </span>
                ) : null}
              </div>
              <div className="flex items-center gap-2">
                {isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
                ) : null}
                <Switch
                  checked={enabled}
                  disabled={isAdmin || !canToggle || isPending}
                  aria-label={`${labelFor(cell.module_code)} access`}
                  onCheckedChange={(next: boolean) =>
                    onToggle(cell.module_code as WritableModuleCode, next)
                  }
                />
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
