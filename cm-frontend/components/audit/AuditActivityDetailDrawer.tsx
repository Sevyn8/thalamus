"use client";

import { Drawer } from "@/components/shared/Drawer";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { Skeleton } from "@/components/shared/Skeleton";
import { Chip } from "@/components/shared/Chips";
import { useAuditActivity } from "@/lib/hooks/use-audit";
import type { AuditActivityDetail } from "@/lib/api/audit";

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function MetadataRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-3 gap-3 py-2">
      <dt className="col-span-1 text-label text-foreground-muted">{label}</dt>
      <dd className="col-span-2 text-body break-all">{children}</dd>
    </div>
  );
}

function Body({ detail }: { detail: AuditActivityDetail }) {
  return (
    <div className="flex flex-col gap-4 py-4">
      <section>
        <h4 className="mb-2 text-subheading">Event</h4>
        <dl className="divide-y divide-border">
          <MetadataRow label="Timestamp">
            {formatTimestamp(detail.timestamp)}
          </MetadataRow>
          <MetadataRow label="Action">
            {detail.action_label}
            <span className="ml-2 text-caption text-foreground-subtle">
              ({detail.action})
            </span>
          </MetadataRow>
          <MetadataRow label="Result">
            <Chip
              tone={detail.result_type === "SUCCESS" ? "green" : "red"}
            >
              {detail.result_label}
            </Chip>
            <span className="ml-2 text-caption text-foreground-subtle">
              ({detail.result_type})
            </span>
          </MetadataRow>
          <MetadataRow label="Resource type">
            {detail.resource_type}
          </MetadataRow>
          <MetadataRow label="Resource subtype">
            {detail.resource_subtype ?? "—"}
          </MetadataRow>
          <MetadataRow label="Resource">
            {detail.resource_label ?? "—"}
          </MetadataRow>
          <MetadataRow label="Resource id">
            <code className="text-caption">{detail.resource_id ?? "—"}</code>
          </MetadataRow>
        </dl>
      </section>

      <section>
        <h4 className="mb-2 text-subheading">Actor</h4>
        <dl className="divide-y divide-border">
          <MetadataRow label="Display name">
            {detail.actor_display_name}
          </MetadataRow>
          <MetadataRow label="Organization">
            {detail.actor_organization_name}
          </MetadataRow>
          <MetadataRow label="Roles">
            {detail.actor_roles}
          </MetadataRow>
          <MetadataRow label="User type">
            <Chip tone={detail.actor_user_type === "PLATFORM" ? "blue" : "grey"}>
              {detail.actor_user_type}
            </Chip>
          </MetadataRow>
          <MetadataRow label="User id">
            <code className="text-caption">{detail.actor_user_id}</code>
          </MetadataRow>
          <MetadataRow label="Tenant">
            {detail.tenant_name ?? "—"}
          </MetadataRow>
          <MetadataRow label="Tenant id">
            <code className="text-caption">{detail.tenant_id ?? "—"}</code>
          </MetadataRow>
        </dl>
      </section>

      <section>
        <h4 className="mb-2 text-subheading">Request</h4>
        <dl className="divide-y divide-border">
          <MetadataRow label="Request id">
            <code className="text-caption">{detail.request_id}</code>
          </MetadataRow>
          <MetadataRow label="Audit id">
            <code className="text-caption">{detail.id}</code>
          </MetadataRow>
        </dl>
      </section>

      <section>
        <h4 className="mb-2 text-subheading">Details</h4>
        {detail.details && Object.keys(detail.details).length > 0 ? (
          <pre className="overflow-x-auto rounded-md border border-border bg-surface p-3 text-caption">
            {JSON.stringify(detail.details, null, 2)}
          </pre>
        ) : (
          <p className="text-caption text-foreground-muted">No payload.</p>
        )}
      </section>
    </div>
  );
}

export type AuditActivityDetailDrawerProps = {
  activityId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function AuditActivityDetailDrawer({
  activityId,
  open,
  onOpenChange,
}: AuditActivityDetailDrawerProps) {
  const query = useAuditActivity(activityId ?? undefined);

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="Audit activity"
      subtitle={activityId ? `Audit ID ${activityId.slice(0, 8)}…` : undefined}
      width="lg"
    >
      {!activityId ? null : query.isLoading ? (
        <div className="py-4">
          <Skeleton variant="text" count={8} />
        </div>
      ) : query.isError ? (
        <ErrorInline
          message="Could not load this audit activity."
          onRetry={() => query.refetch()}
        />
      ) : query.data ? (
        <Body detail={query.data} />
      ) : null}
    </Drawer>
  );
}
