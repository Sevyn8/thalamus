"use client";

import { formatDistanceToNow } from "date-fns";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Drawer } from "@/components/shared/Drawer";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { StatusChip } from "@/components/shared/Chips";
import { comingInV1 } from "@/components/shared/ComingInV1Toast";
import { AuditActivityCompactRow } from "@/components/audit/AuditActivityCompactRow";
import { initials, avatarTone } from "@/lib/utils/initials";
import { usePlatformUser } from "@/lib/hooks/use-platform-users";
import { useAuditActivities } from "@/lib/hooks/use-audit";
import { cn } from "@/lib/utils";
import type { PlatformUser } from "@/types/api";

function dateLabel(iso: string | null): string {
  if (!iso) return "—";
  return formatDistanceToNow(new Date(iso), { addSuffix: true });
}

// Per-user Activity section is scoped via the `actor_user_id` filter.
// The compact row variant fits the drawer's denser vertical layout.

function Body({ user }: { user: PlatformUser }) {
  const activity = useAuditActivities({
    actor_user_id: user.id,
    limit: 10,
  });
  const rows = activity.data?.items ?? [];

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
          <div className="truncate text-xs text-muted-foreground">Platform (Sevyn8)</div>
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
        ) : rows.length === 0 ? (
          <span className="text-sm text-muted-foreground">
            No recent activity for this user.
          </span>
        ) : (
          <ul className="flex flex-col">
            {rows.map((row) => (
              <AuditActivityCompactRow
                key={row.id}
                row={row}
                onClick={() => {
                  // Activity row click within a drawer is a soft
                  // affordance for v0 — no in-place audit-detail
                  // drawer yet (the audit surface owns that flow).
                }}
              />
            ))}
          </ul>
        )}
      </div>

    </div>
  );
}

export type PlatformUserDetailDrawerProps = {
  userId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function PlatformUserDetailDrawer({
  userId,
  open,
  onOpenChange,
}: PlatformUserDetailDrawerProps) {
  const q = usePlatformUser(userId ?? "");

  const status = q.data?.status;
  const showSuspend = status === "ACTIVE";
  const showReactivate = status === "SUSPENDED";
  const showResendInvite = status === "INVITED";

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      width="lg"
      title={q.data?.full_name ?? "User"}
      subtitle={q.data?.email ?? undefined}
      footer={
        <div className="flex flex-wrap items-center justify-end gap-2">
          {showResendInvite ? (
            <Button variant="outline" onClick={() => comingInV1("Resend invitation")}>
              Resend invitation
            </Button>
          ) : null}
          {showSuspend ? (
            <Button variant="destructive" onClick={() => comingInV1("Suspend user")}>
              Suspend
            </Button>
          ) : null}
          {showReactivate ? (
            <Button
              className="bg-success text-white hover:bg-success/90"
              onClick={() => comingInV1("Reactivate user")}
            >
              Reactivate
            </Button>
          ) : null}
          <Button onClick={() => comingInV1("Edit user")}>Edit</Button>
        </div>
      }
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
