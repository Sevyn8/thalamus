"use client";

import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Drawer } from "@/components/shared/Drawer";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { StatusChip, TierChip } from "@/components/shared/Chips";
import { initials, avatarTone } from "@/lib/utils/initials";
import {
  useActivateTenant,
  useSuspendTenant,
  useTenant,
} from "@/lib/hooks/use-tenants";
import { useCanDo } from "@/lib/auth/use-me-can-do";
import { cn } from "@/lib/utils";
import type { TenantDetail } from "@/types/api";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function formatRevenue(usd: string | null): string {
  if (!usd) return "—";
  const n = Number(usd);
  if (Number.isNaN(n)) return "—";
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })} / mo`;
}

function MetadataRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">{children}</span>
    </div>
  );
}

function Body({ tenant }: { tenant: TenantDetail }) {
  return (
    <div className="flex flex-col gap-4 pt-2">
      <div className="flex items-center gap-3">
        <span
          className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-sm font-semibold",
            avatarTone(tenant.name),
          )}
          aria-hidden="true"
        >
          {initials(tenant.name)}
        </span>
        <div className="flex min-w-0 flex-col">
          <div className="truncate font-medium">{tenant.name}</div>
          <div className="truncate text-xs text-muted-foreground">
            {tenant.display_code ?? "—"} · {tenant.country ?? "—"} · {tenant.region}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {tenant.tier ? <TierChip tier={tenant.tier} /> : null}
        <StatusChip status={tenant.status} />
      </div>

      <Separator />

      <div className="divide-y divide-border">
        <MetadataRow label="Industry">
          {tenant.industry?.toLowerCase().replace(/_/g, " ") ?? "—"}
        </MetadataRow>
        <MetadataRow label="Stores">{tenant.num_stores.toLocaleString()}</MetadataRow>
        <MetadataRow label="Users">{tenant.num_users_active.toLocaleString()}</MetadataRow>
        <MetadataRow label="MRR">{formatRevenue(tenant.monthly_revenue_usd)}</MetadataRow>
        <MetadataRow label="Onboarded">{formatDate(tenant.created_at)}</MetadataRow>
        <MetadataRow label="Last updated">{formatDate(tenant.updated_at)}</MetadataRow>
        <MetadataRow label="Primary contact">
          {tenant.primary_contact_name ? (
            <span className="flex flex-col items-end">
              <span>{tenant.primary_contact_name}</span>
              {tenant.contact_email ? (
                <span className="text-xs text-muted-foreground">{tenant.contact_email}</span>
              ) : null}
            </span>
          ) : (
            "—"
          )}
        </MetadataRow>
      </div>

      <Separator />

      <div className="flex flex-col gap-2">
        <div className="text-label text-muted-foreground">
          Modules
        </div>
        <ul className="flex flex-col gap-1">
          {tenant.modules.map((m) => (
            <li
              key={m.code}
              className="flex items-center justify-between rounded-md bg-muted/30 px-2 py-1.5 text-sm"
            >
              <span>{m.name}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export type TenantDetailDrawerProps = {
  tenantId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function TenantDetailDrawer({ tenantId, open, onOpenChange }: TenantDetailDrawerProps) {
  const router = useRouter();
  const q = useTenant(tenantId ?? "");
  const suspendMutation = useSuspendTenant();
  const activateMutation = useActivateTenant();

  // Phase 5n.5 tuple split: lifecycle (suspend/activate) is gated by
  // backend on ADMIN.TENANTS.OVERRIDE.GLOBAL per
  // src/admin_backend/routers/v1/tenants.py:363-366 (activate) and
  // line 409+ (suspend). Do NOT collapse this to CONFIGURE — that
  // gate is for create/edit, not lifecycle transitions. SUPER_ADMIN
  // holds both grants today; future TENANT-scoped admins (Phase 5g)
  // may hold only one. Code comment is load-bearing — preserve.
  const canManageTenantLifecycle = useCanDo(
    "ADMIN",
    "TENANTS",
    "OVERRIDE",
    "GLOBAL",
  );

  // Edit gate (PATCH /tenants/{id}); tuple matches POST per
  // src/admin_backend/routers/v1/tenants.py:137-140 (POST) and
  // 310-313 (PATCH). Slice 7 item 2: Edit tenant routes to the wizard
  // edit surface (the retired EditTenantModal's replacement); the wizard
  // route enforces the same CONFIGURE gate, and this pre-flight keeps the
  // denial path honest before navigating.
  const canEditTenant = useCanDo(
    "ADMIN",
    "TENANTS",
    "CONFIGURE",
    "GLOBAL",
  );

  const lifecycleInFlight =
    suspendMutation.isPending || activateMutation.isPending;

  function onSuspendClick() {
    if (!tenantId) return;
    if (canManageTenantLifecycle.data?.allowed === false) {
      toast.error("You don't have permission to suspend tenants.");
      return;
    }
    suspendMutation.mutate(tenantId, {
      onSuccess: () => toast.success("Tenant suspended"),
      onError: () =>
        toast.error("Could not suspend tenant. Please try again."),
    });
  }

  function onActivateClick() {
    if (!tenantId) return;
    if (canManageTenantLifecycle.data?.allowed === false) {
      toast.error("You don't have permission to change tenant status.");
      return;
    }
    // Backend's allowed_sources for ACTIVE = {TRIAL, SUSPENDED}. The
    // user-facing verb differs by source: TRIAL → ACTIVE reads as
    // "activate" (one-way promotion; tenant never returns to TRIAL);
    // SUSPENDED → ACTIVE reads as "resume" (restoration after a pause).
    const isPromotion = q.data?.status === "TRIAL";
    activateMutation.mutate(tenantId, {
      onSuccess: () =>
        toast.success(isPromotion ? "Tenant activated" : "Tenant resumed"),
      onError: () =>
        toast.error(
          isPromotion
            ? "Could not activate tenant. Please try again."
            : "Could not resume tenant. Please try again.",
        ),
    });
  }

  function onEditClick() {
    if (!tenantId) return;
    if (canEditTenant.data?.allowed === false) {
      toast.error("You don't have permission to edit tenants.");
      return;
    }
    // Route to the wizard, which opens in edit mode for a non-ONBOARDING
    // tenant (and in resume-onboarding mode for an ONBOARDING one).
    router.push(`/superadmin/tenants/onboard/${tenantId}`);
  }

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      width="lg"
      title={q.data?.name ?? "Tenant"}
      subtitle={q.data?.display_code ?? undefined}
      footer={
        // Lifecycle button matrix mirrors the backend's allowed_sources:
        //   ONBOARDING → Resume onboarding (Slice 6; suspend/activate would
        //                409, so they are correctly absent)
        //   TRIAL      → Activate (positive) + Suspend (destructive)
        //   ACTIVE     → Suspend
        //   SUSPENDED  → Resume
        //   TERMINATED → no action (off-graph backend-side)
        <div className="flex items-center justify-end gap-2">
          {q.data?.status === "ONBOARDING" ? (
            <Button
              onClick={() =>
                router.push(`/superadmin/tenants/onboard/${tenantId}`)
              }
            >
              Resume onboarding
            </Button>
          ) : null}
          {q.data?.status === "TRIAL" ? (
            <>
              <Button
                className="bg-success text-white hover:bg-success/90"
                onClick={onActivateClick}
                disabled={lifecycleInFlight}
              >
                {activateMutation.isPending ? (
                  <>
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    Activating...
                  </>
                ) : (
                  "Activate"
                )}
              </Button>
              <Button
                variant="destructive"
                onClick={onSuspendClick}
                disabled={lifecycleInFlight}
              >
                {suspendMutation.isPending ? (
                  <>
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    Suspending...
                  </>
                ) : (
                  "Suspend"
                )}
              </Button>
            </>
          ) : null}
          {q.data?.status === "ACTIVE" ? (
            <Button
              variant="destructive"
              onClick={onSuspendClick}
              disabled={lifecycleInFlight}
            >
              {suspendMutation.isPending ? (
                <>
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  Suspending...
                </>
              ) : (
                "Suspend"
              )}
            </Button>
          ) : null}
          {q.data?.status === "SUSPENDED" ? (
            <Button
              className="bg-success text-white hover:bg-success/90"
              onClick={onActivateClick}
              disabled={lifecycleInFlight}
            >
              {activateMutation.isPending ? (
                <>
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  Resuming...
                </>
              ) : (
                "Resume"
              )}
            </Button>
          ) : null}
          <Button onClick={onEditClick}>Edit tenant</Button>
        </div>
      }
    >
      {q.isLoading ? (
        <div className="flex flex-col gap-3 pt-2">
          <Skeleton variant="rect" />
          <Skeleton variant="row" count={4} />
        </div>
      ) : q.error ? (
        <ErrorInline message="Could not load tenant." onRetry={() => q.refetch()} />
      ) : q.data ? (
        <Body tenant={q.data} />
      ) : null}
    </Drawer>
  );
}
