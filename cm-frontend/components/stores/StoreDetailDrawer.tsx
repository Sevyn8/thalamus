"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Drawer } from "@/components/shared/Drawer";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { StatusChip } from "@/components/shared/Chips";
import { initials, avatarTone } from "@/lib/utils/initials";
import { useStore, useSetStoreStatus } from "@/lib/hooks/use-stores";
import { useCanDo } from "@/lib/auth/use-me-can-do";
import { cn } from "@/lib/utils";
import { EditStoreModal } from "./EditStoreModal";
import type { StoreDetail, StoreStatus } from "@/types/api";

// Phase 5-stores: state-transition matrix mirrors the backend's
// `TRANSITION_MATRIX` (admin_backend/repositories/stores.py:93-98).
// Liberal 9-cell graph: all transitions allowed EXCEPT `*→OPENING`.
// CLOSED is reversible. Same-state rejected server-side; we filter
// it out client-side so the dropdown never offers it.
const STORE_TRANSITIONS: Record<StoreStatus, StoreStatus[]> = {
  OPENING: ["ACTIVE", "INACTIVE", "CLOSED"],
  ACTIVE: ["INACTIVE", "CLOSED"],
  INACTIVE: ["ACTIVE", "CLOSED"],
  CLOSED: ["ACTIVE", "INACTIVE"],
};

const STATUS_LABEL: Record<StoreStatus, string> = {
  OPENING: "Opening",
  ACTIVE: "Active",
  INACTIVE: "Inactive",
  CLOSED: "Closed",
};

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
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
    <div className="flex items-start justify-between gap-4 py-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">{children}</span>
    </div>
  );
}

function Body({
  store,
  onEdit,
  onTransition,
  transitionInFlight,
  canEdit,
}: {
  store: StoreDetail;
  onEdit: () => void;
  onTransition: (target: StoreStatus) => void;
  transitionInFlight: boolean;
  canEdit: boolean;
}) {
  const validTargets = STORE_TRANSITIONS[store.status];

  return (
    <div className="flex flex-col gap-4 pt-2">
      <div className="flex items-center gap-3">
        <span
          className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-sm font-semibold",
            avatarTone(store.name),
          )}
          aria-hidden="true"
        >
          {initials(store.name)}
        </span>
        <div className="flex min-w-0 flex-col">
          <div className="truncate font-medium">{store.name}</div>
          <div className="truncate text-xs text-muted-foreground">
            {store.tenant_name}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <StatusChip status={store.status} />
      </div>

      <Separator />

      <div className="divide-y divide-border">
        <MetadataRow label="Store code">
          <span className="font-mono">{store.store_code ?? "—"}</span>
        </MetadataRow>
        <MetadataRow label="Country">{store.country}</MetadataRow>
        <MetadataRow label="Timezone">{store.timezone}</MetadataRow>
        <MetadataRow label="Currency">{store.currency}</MetadataRow>
        <MetadataRow label="Tax treatment">
          {store.tax_treatment === "EXCLUSIVE" ? "Exclusive" : "Inclusive"}
        </MetadataRow>
        <MetadataRow label="Address">{store.address ?? "—"}</MetadataRow>
        <MetadataRow label="Coordinates">
          {store.latitude && store.longitude
            ? `${store.latitude}, ${store.longitude}`
            : "—"}
        </MetadataRow>
        <MetadataRow label="Created">{formatDate(store.created_at)}</MetadataRow>
        <MetadataRow label="Last updated">
          {formatDate(store.updated_at)}
        </MetadataRow>
        {store.closed_at ? (
          <MetadataRow label="Closed">{formatDate(store.closed_at)}</MetadataRow>
        ) : null}
      </div>

      <Separator />

      <div className="flex flex-col gap-2">
        <div className="text-label text-muted-foreground">Change status</div>
        <div className="flex flex-wrap gap-2">
          {validTargets.map((target) => (
            <Button
              key={target}
              variant="outline"
              size="sm"
              disabled={transitionInFlight || !canEdit}
              onClick={() => onTransition(target)}
            >
              → {STATUS_LABEL[target]}
            </Button>
          ))}
          {transitionInFlight ? (
            <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Updating...
            </span>
          ) : null}
        </div>
        {!canEdit ? (
          <p className="text-xs text-muted-foreground">
            You don&apos;t have permission to change store status.
          </p>
        ) : null}
      </div>
    </div>
  );
}

export type StoreDetailDrawerProps = {
  storeId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function StoreDetailDrawer({
  storeId,
  open,
  onOpenChange,
}: StoreDetailDrawerProps) {
  const q = useStore(storeId ?? "");
  const setStatusMutation = useSetStoreStatus();
  const [editOpen, setEditOpen] = useState(false);

  // Single permission tuple covers every Stores write (patch +
  // set-status). PLATFORM passes via GLOBAL→TENANT cascade per
  // backend's LD9. anchor_dep on the backend filters cross-tenant
  // probes by TENANT callers.
  const canConfigureStores = useCanDo(
    "ADMIN",
    "STORES",
    "CONFIGURE",
    "TENANT",
  );
  const canEdit = canConfigureStores.data?.allowed !== false;

  function onTransition(target: StoreStatus) {
    if (!storeId) return;
    if (!canEdit) {
      toast.error("You don't have permission to change store status.");
      return;
    }
    setStatusMutation.mutate(
      { id: storeId, target_status: target },
      {
        onSuccess: () =>
          toast.success(`Store status changed to ${STATUS_LABEL[target]}`),
        onError: () =>
          toast.error("Could not change status. Please try again."),
      },
    );
  }

  function onEditClick() {
    if (!canEdit) {
      toast.error("You don't have permission to edit stores.");
      return;
    }
    setEditOpen(true);
  }

  return (
    <>
      <Drawer
        open={open}
        onOpenChange={onOpenChange}
        width="lg"
        title={q.data?.name ?? "Store"}
        subtitle={q.data?.tenant_name ?? undefined}
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button onClick={onEditClick} disabled={!canEdit}>
              Edit store
            </Button>
          </div>
        }
      >
        {q.isLoading ? (
          <div className="flex flex-col gap-3 pt-2">
            <Skeleton variant="rect" />
            <Skeleton variant="row" count={4} />
          </div>
        ) : q.error ? (
          <ErrorInline
            message="Could not load store."
            onRetry={() => q.refetch()}
          />
        ) : q.data ? (
          <Body
            store={q.data}
            onEdit={onEditClick}
            onTransition={onTransition}
            transitionInFlight={setStatusMutation.isPending}
            canEdit={canEdit}
          />
        ) : null}
      </Drawer>

      {q.data ? (
        <EditStoreModal
          open={editOpen}
          onOpenChange={setEditOpen}
          store={q.data}
        />
      ) : null}
    </>
  );
}
