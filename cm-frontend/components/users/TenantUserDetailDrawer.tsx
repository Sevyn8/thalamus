"use client";

import { useState } from "react";
import { toast } from "sonner";
import { formatDistanceToNow } from "date-fns";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Drawer } from "@/components/shared/Drawer";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { StatusChip } from "@/components/shared/Chips";
import { comingInV1 } from "@/components/shared/ComingInV1Toast";
import { ConfirmDestructive } from "@/components/shared/ConfirmDestructive";
import { EditTenantUserModal } from "@/components/users/EditTenantUserModal";
import { AuditActivityCompactRow } from "@/components/audit/AuditActivityCompactRow";
import { initials, avatarTone } from "@/lib/utils/initials";
import {
  useActivateTenantUser,
  useSuspendTenantUser,
  useTenantUser,
} from "@/lib/hooks/use-tenant-users";
import { useTenant } from "@/lib/hooks/use-tenants";
import { useAuditActivities } from "@/lib/hooks/use-audit";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { useCanDo } from "@/lib/auth/use-me-can-do";
import { cn } from "@/lib/utils";
import type { TenantUser } from "@/types/api";

// Platform personas can impersonate any tenant user; tenant personas
// cannot. Backend's TenantUserRead doesn't carry role data so we can't
// gate further on target-is-admin (the old hybrid User type's
// `roles[]` is gone in v0). When backend extends the schema, this
// check tightens to platform-AND-target-is-not-admin.
//
// Phase 5i.1 (2026-05-25): per-user Activity section restored via the
// actor_user_id filter shipped in Step 6.16.6. Closes 5h.4 deferral.

function dateLabel(iso: string | null): string {
  if (!iso) return "—";
  return formatDistanceToNow(new Date(iso), { addSuffix: true });
}

function Body({ user }: { user: TenantUser }) {
  const tenantQuery = useTenant(user.tenant_id);
  const tenantName = tenantQuery.data?.name ?? "—";
  const activity = useAuditActivities({
    actor_user_id: user.id,
    limit: 10,
  });
  const activityRows = activity.data?.items ?? [];

  return (
    <div className="flex flex-col gap-4 pt-2">
      <div className="flex items-center gap-3">
        <span
          className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-sm font-semibold",
            avatarTone(user.full_name),
          )}
          aria-hidden="true"
        >
          {initials(user.full_name)}
        </span>
        <div className="flex min-w-0 flex-col">
          <div className="truncate font-medium">{user.full_name}</div>
          <div className="truncate text-xs text-muted-foreground">{user.email}</div>
          <div className="truncate text-xs text-muted-foreground">{tenantName}</div>
        </div>
      </div>

      <Separator />

      <div className="grid grid-cols-2 gap-3 text-sm">
        <div className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wide text-muted-foreground">Status</span>
          <span><StatusChip status={user.status} /></span>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wide text-muted-foreground">Last updated</span>
          <span>{dateLabel(user.updated_at)}</span>
        </div>
      </div>

      <Separator />

      <div className="flex flex-col gap-2">
        <div className="text-label text-muted-foreground">Lifecycle</div>
        <dl className="flex flex-col gap-1.5 text-sm">
          <div className="flex items-baseline justify-between gap-4">
            <dt className="text-muted-foreground">Invited</dt>
            <dd>{dateLabel(user.invited_at)}</dd>
          </div>
          <div className="flex items-baseline justify-between gap-4">
            <dt className="text-muted-foreground">Accepted invitation</dt>
            <dd>{dateLabel(user.invitation_accepted_at)}</dd>
          </div>
          {user.suspended_at ? (
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-muted-foreground">Suspended</dt>
              <dd>{dateLabel(user.suspended_at)}</dd>
            </div>
          ) : null}
          <div className="flex items-baseline justify-between gap-4">
            <dt className="text-muted-foreground">Created</dt>
            <dd>{dateLabel(user.created_at)}</dd>
          </div>
        </dl>
      </div>

      <Separator />

      <div className="flex flex-col gap-2">
        <div className="text-label text-muted-foreground">Recent activity</div>
        {activity.isLoading ? (
          <Skeleton variant="row" count={3} />
        ) : activity.error ? (
          <ErrorInline
            message="Could not load activity."
            onRetry={() => activity.refetch()}
          />
        ) : activityRows.length === 0 ? (
          <span className="text-sm text-muted-foreground">
            No recent activity for this user.
          </span>
        ) : (
          <ul className="flex flex-col">
            {activityRows.map((row) => (
              <AuditActivityCompactRow
                key={row.id}
                row={row}
                onClick={() => {
                  // Soft affordance for v0 — no in-place audit-detail
                  // drawer from within this user drawer.
                }}
              />
            ))}
          </ul>
        )}
      </div>

    </div>
  );
}

function FooterActions({ user }: { user: TenantUser }) {
  const me = useAuthSnapshot();
  const canImpersonate = me?.user.userType === "PLATFORM";

  // All four writes gate on the same multi-audience tuple
  // ADMIN.USERS.CONFIGURE.TENANT per
  // src/admin_backend/routers/v1/tenant_users.py:391-394 (create),
  // 454-457 (patch), 519-522 (suspend), 575-578 (activate). PLATFORM
  // passes via GLOBAL→TENANT cascade; OWNER via direct TENANT grant.
  const canManageTenantUsers = useCanDo(
    "ADMIN",
    "USERS",
    "CONFIGURE",
    "TENANT",
  );
  const canWrite = canManageTenantUsers.data?.allowed !== false;

  const suspendMutation = useSuspendTenantUser();
  const activateMutation = useActivateTenantUser();
  const [confirmSuspendOpen, setConfirmSuspendOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);

  const status = user.status;
  const showSuspend = status === "ACTIVE" && canWrite;
  const showReactivate = status === "SUSPENDED" && canWrite;
  const showResendInvite = status === "INVITED";
  const inFlight = suspendMutation.isPending || activateMutation.isPending;

  async function onSuspendConfirm() {
    try {
      await suspendMutation.mutateAsync(user.id);
      toast.success(`${user.full_name} suspended`);
    } catch {
      toast.error("Could not suspend user. Please try again.");
    }
  }

  function onReactivateClick() {
    activateMutation.mutate(user.id, {
      onSuccess: () => toast.success(`${user.full_name} reactivated`),
      onError: () =>
        toast.error("Could not reactivate user. Please try again."),
    });
  }

  return (
    <>
      <div className="flex flex-wrap items-center justify-end gap-2">
        {showResendInvite ? (
          <Button variant="outline" onClick={() => comingInV1("Resend invitation")}>
            Resend invitation
          </Button>
        ) : null}
        {canImpersonate ? (
          <Button variant="outline" onClick={() => comingInV1("Impersonate user")}>
            Impersonate
          </Button>
        ) : null}
        {showSuspend ? (
          <Button
            variant="destructive"
            onClick={() => setConfirmSuspendOpen(true)}
            disabled={inFlight}
          >
            {suspendMutation.isPending ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                Suspending…
              </>
            ) : (
              "Suspend"
            )}
          </Button>
        ) : null}
        {showReactivate ? (
          <Button
            className="bg-success text-white hover:bg-success/90"
            onClick={onReactivateClick}
            disabled={inFlight}
          >
            {activateMutation.isPending ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                Reactivating…
              </>
            ) : (
              "Reactivate"
            )}
          </Button>
        ) : null}
        <Button
          onClick={() => {
            if (!canWrite) {
              toast.error("You don't have permission to edit this user.");
              return;
            }
            setEditOpen(true);
          }}
          disabled={inFlight}
        >
          Edit
        </Button>
      </div>

      <ConfirmDestructive
        open={confirmSuspendOpen}
        onOpenChange={setConfirmSuspendOpen}
        title="Suspend user?"
        description={
          <>
            <p>
              The user will be unable to sign in until reactivated. Their
              role assignments and activity history are preserved.
            </p>
            <p className="mt-2">
              Type the user&apos;s name <code className="text-foreground">{user.full_name}</code> to confirm.
            </p>
          </>
        }
        confirmText={user.full_name}
        confirmLabel="Suspend user"
        onConfirm={onSuspendConfirm}
      />

      <EditTenantUserModal
        open={editOpen}
        onOpenChange={setEditOpen}
        user={user}
      />
    </>
  );
}

export type TenantUserDetailDrawerProps = {
  userId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function TenantUserDetailDrawer({
  userId,
  open,
  onOpenChange,
}: TenantUserDetailDrawerProps) {
  const q = useTenantUser(userId ?? "");

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      width="lg"
      title={q.data?.full_name ?? "User"}
      subtitle={q.data?.email ?? undefined}
      footer={q.data ? <FooterActions user={q.data} /> : null}
    >
      {q.isLoading ? (
        <div className="flex flex-col gap-3 pt-2">
          <Skeleton variant="rect" />
          <Skeleton variant="row" count={5} />
        </div>
      ) : q.error ? (
        <ErrorInline message="Could not load user." onRetry={() => q.refetch()} />
      ) : q.data ? (
        <Body user={q.data} />
      ) : null}
    </Drawer>
  );
}
