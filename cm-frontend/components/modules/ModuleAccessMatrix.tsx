"use client";

// POSITION-ALIGNED ARRAY INVARIANT: row.cells[i] under modules.items[i].
// Anchor pair differs from PermissionMatrixView (which is roles[] vs
// row.cells[]); same discipline applies. If you sort/filter rows or
// modules, MAINTAIN array alignment. Mismatched arrays render
// silently wrong. Backend ships modules + cells in identical order
// (lookups.display_order ASC); MSW mirrors via CANONICAL_ORDER.

import { useState } from "react";
import { Loader2, Lock } from "lucide-react";
import { toast } from "sonner";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { TierChip } from "@/components/shared/Chips";
import { useCanDo } from "@/lib/auth/use-me-can-do";
import {
  useEnableModuleAccess,
  useDisableModuleAccess,
} from "@/lib/hooks/use-modules";
import { initials, avatarTone } from "@/lib/utils/initials";
import { cn } from "@/lib/utils";
import type { WritableModuleCode } from "@/lib/api/modules";
import type { MatrixRow, ModuleCard } from "@/types/api";

const ADMIN_TOOLTIP =
  "Admin module is required for every tenant and cannot be disabled.";

export type ModuleAccessMatrixProps = {
  rows: MatrixRow[];
  modules: ModuleCard[];
  loading: boolean;
  hasError: boolean;
  onRetry: () => void;
};

// Phase 5e.3: rewritten to consume backend's MatrixResponse shape.
// cells[] are now {module_code, status: "ENABLED" | "DISABLED"}
// rather than the pre-5e3 {code, enabled, enabled_at}. The
// enabled_at field had no backend equivalent and is dropped.
// Phase 5j: cell click wires to real backend enable/disable mutations
// (Step 6.15 endpoints). Server-wait UX, no optimistic state.
export function ModuleAccessMatrix({
  rows,
  modules,
  loading,
  hasError,
  onRetry,
}: ModuleAccessMatrixProps) {
  // Phase 5j: useCanDo pre-flight gate.
  // Module Access enable/disable shares the tenant lifecycle permission
  // tuple (ADMIN.TENANTS.OVERRIDE.GLOBAL) per
  // step-6_15-impl-2026-05-15.md LD3. The reuse is deliberate
  // (SUPER_ADMIN-only, same privilege boundary as tenant suspend/
  // activate). Do NOT "fix" this to look more module-access-specific —
  // Sanjeev's backend gates exclusively on this tuple. See BUILD_PLAN
  // Sanjeev queue for the Phase 5g aliasing concern.
  const canToggleModuleAccess = useCanDo(
    "ADMIN",
    "TENANTS",
    "OVERRIDE",
    "GLOBAL",
  );

  const enableMutation = useEnableModuleAccess();
  const disableMutation = useDisableModuleAccess();

  // Tracks which cell is in-flight: `${tenantId}:${moduleCode}`. Set
  // when the user clicks; cleared on settle. Cell shows a spinner +
  // muted color during this window.
  const [pendingKeys, setPendingKeys] = useState<Set<string>>(new Set());

  function handleToggle(
    tenantId: string,
    code: WritableModuleCode,
    currentlyEnabled: boolean,
  ) {
    // useCanDo pre-flight gate per 5f.W.2 demo consumer pattern.
    // data === undefined during in-flight (v0 expedient: action proceeds;
    // server is the security boundary; see Finding #20 + use-me-can-do.ts).
    if (canToggleModuleAccess.data?.allowed === false) {
      toast.error("You don't have permission to toggle module access.");
      return;
    }
    const key = `${tenantId}:${code}`;
    setPendingKeys((prev) => {
      const next = new Set(prev);
      next.add(key);
      return next;
    });
    const mutation = currentlyEnabled ? disableMutation : enableMutation;
    mutation.mutate(
      { tenantId, moduleCode: code },
      {
        onError: () => {
          toast.error(
            `Could not ${currentlyEnabled ? "disable" : "enable"} module. Please try again.`,
          );
        },
        onSettled: () => {
          setPendingKeys((prev) => {
            if (!prev.has(key)) return prev;
            const next = new Set(prev);
            next.delete(key);
            return next;
          });
        },
      },
    );
  }

  if (loading) {
    return <Skeleton variant="row" count={7} />;
  }
  if (hasError) {
    return (
      <ErrorInline message="Could not load module access matrix." onRetry={onRetry} />
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="min-w-[260px] px-4 text-label text-muted-foreground">
              Tenant
            </TableHead>
            {modules.map((m) => (
              <TableHead
                key={m.module_code}
                className="min-w-[120px] text-center text-label text-muted-foreground"
              >
                {m.module_label}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.tenant_id} className="even:bg-muted/20">
              <TableCell className="px-4 py-3">
                <div className="flex items-center gap-3">
                  <span
                    className={cn(
                      "flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-xs font-semibold",
                      avatarTone(row.name),
                    )}
                    aria-hidden="true"
                  >
                    {initials(row.name)}
                  </span>
                  <div className="flex min-w-0 flex-col">
                    <span className="truncate text-sm font-medium">
                      {row.name}
                    </span>
                    {row.tier ? (
                      <span className="mt-0.5">
                        <TierChip tier={row.tier} />
                      </span>
                    ) : null}
                  </div>
                </div>
              </TableCell>
              {modules.map((m, i) => {
                // Position-aligned cell lookup via index — matches the
                // backend's hard invariant. Defensive id check guards
                // against ordering drift if a future client-side
                // re-shape ever happens.
                const cell = row.cells[i];
                const enabled =
                  cell?.module_code === m.module_code
                    ? cell.status === "ENABLED"
                    : false;
                const key = `${row.tenant_id}:${m.module_code}`;
                const isPending = pendingKeys.has(key);
                // Toggleability is catalog-driven: every module the matrix
                // ships toggles like any other (DIS included, now that it is
                // a real backend module). ADMIN is the sole exception and
                // keeps its lock, mirroring the backend DDL constraint that
                // ADMIN cannot be disabled. There is no page-local allowlist
                // gating which modules toggle (a stale one predating DIS was
                // the cause of the inert DIS toggle).
                const isAdmin = m.module_code === "ADMIN";

                if (isAdmin) {
                  return (
                    <TableCell key={m.module_code} className="text-center">
                      <span
                        title={ADMIN_TOOLTIP}
                        className="inline-flex items-center gap-2"
                      >
                        <Switch checked disabled />
                        <Lock
                          className="h-3.5 w-3.5 text-muted-foreground"
                          aria-hidden="true"
                        />
                      </span>
                    </TableCell>
                  );
                }

                return (
                  <TableCell key={m.module_code} className="text-center">
                    <span
                      className={cn(
                        "inline-flex items-center gap-2",
                        isPending && "opacity-60",
                      )}
                    >
                      <Switch
                        checked={enabled}
                        disabled={isPending}
                        onCheckedChange={() =>
                          handleToggle(
                            row.tenant_id,
                            m.module_code as WritableModuleCode,
                            enabled,
                          )
                        }
                        aria-label={`${enabled ? "Disable" : "Enable"} ${m.module_label} for ${row.name}`}
                      />
                      {isPending ? (
                        <Loader2
                          className="h-3.5 w-3.5 animate-spin text-muted-foreground"
                          aria-hidden="true"
                        />
                      ) : null}
                    </span>
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
