"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Modal } from "@/components/shared/Modal";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import { recordAuditEvent } from "@/lib/dis/audit";
import { useUpdateSource } from "@/lib/dis/hooks/use-sources";
import { useTenantUsers } from "@/lib/hooks/use-tenant-users";
import { cn } from "@/lib/utils";
import type { Source } from "@/types/dis";

// Phase 5c.2c2: admin reassign-ownership modal. Visible only to
// Platform personas (gated by parent SourceLifecycleActions). Uses
// Ithina's existing useTenantUsers hook to populate the picker —
// same cross-product reuse pattern as 5c.2b1's OrgNodePicker. Native
// <select> picker per A9 (small tenant-user counts in v1; richer
// search comes when fixtures grow).
//
// Phase 5f.X: tenant_id namespace consolidated to canonical Sanjeev
// UUIDs across all fixtures + persona catalogue. The historical
// DIS-side vs Ithina-side alias problem no longer exists; source
// rows and tenant-users rows share one ID space.

type Props = {
  source: Source;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function ReassignOwnershipModal({ source, open, onOpenChange }: Props) {
  const usersQuery = useTenantUsers({ tenant_id: source.tenant_id, limit: 200 });
  const update = useUpdateSource(source.id);
  const [selectedUserId, setSelectedUserId] = useState<string>("");
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Reset selection on close path (mirrors ConfirmDestructive's
  // pattern). Avoids the React 19 set-state-in-effect lint by handling
  // reset in the open-change callback rather than an effect.
  function handleOpenChange(next: boolean) {
    if (!next) {
      setSelectedUserId("");
      setSubmitError(null);
    }
    onOpenChange(next);
  }

  const users = usersQuery.data?.items ?? [];
  const previousOwnerId = source.owner_user_id;
  const canSave =
    selectedUserId.length > 0 &&
    selectedUserId !== previousOwnerId &&
    !update.isPending;

  async function onSave() {
    if (!canSave) return;
    setSubmitError(null);
    try {
      await update.mutateAsync({ owner_user_id: selectedUserId });
      recordAuditEvent({
        event_type: "admin_reassign_ownership",
        source_id: source.id,
        source_name: source.name,
        previous_owner_user_id: previousOwnerId,
        new_owner_user_id: selectedUserId,
      });
      toast.success("Ownership reassigned.");
      handleOpenChange(false);
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Reassign failed.");
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={handleOpenChange}
      title="Reassign ownership"
      subtitle={`Choose a new owner for ${source.name}. Current owner: ${source.owner_name ?? "(unassigned)"}.`}
    >
      <div className="flex flex-col gap-4">
        {usersQuery.isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading tenant users…
          </div>
        ) : usersQuery.error ? (
          <p className="text-sm text-danger">Could not load tenant users.</p>
        ) : users.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No users found for this tenant.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            <label className="text-label text-muted-foreground">New owner</label>
            <select
              value={selectedUserId}
              onChange={(e) => setSelectedUserId(e.target.value)}
              className={cn(
                "h-9 rounded-md border border-input bg-background px-2.5 py-1 text-sm",
                "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
                "dark:bg-input/30",
              )}
            >
              <option value="">Select a user…</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name} — {u.email}
                </option>
              ))}
            </select>
          </div>
        )}

        {submitError ? (
          <p className="text-sm text-danger" role="alert">
            {submitError}
          </p>
        ) : null}

        <div className="flex items-center justify-end gap-2 border-t border-border pt-3">
          <Button variant="ghost" onClick={() => handleOpenChange(false)} disabled={update.isPending}>
            Cancel
          </Button>
          <Button onClick={onSave} disabled={!canSave}>
            {update.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Saving…
              </>
            ) : (
              "Reassign"
            )}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
