"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { AlertCircle, Loader2 } from "lucide-react";

import { Modal } from "@/components/shared/Modal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  RoleAssignmentEditor,
  findDuplicateIndexes,
  hasIncompleteRows,
  type RoleAssignmentRow,
} from "@/components/tenant-users/RoleAssignmentEditor";
import { useEditTenantUser } from "@/lib/hooks/use-tenant-users";
import { ApiError } from "@/lib/api/client";
import type {
  RoleAssignmentItem,
  TenantUserPatchPayload,
} from "@/lib/api/tenant-users";
import type { TenantUser } from "@/types/api";
import { cn } from "@/lib/utils";

const FIELD_INPUT_CLASS = cn(
  "h-9 w-full rounded-md border border-input bg-background px-2.5 py-1 text-sm",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
  "dark:bg-input/30",
);

function FieldLabel({
  htmlFor,
  children,
}: {
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <label htmlFor={htmlFor} className="text-xs font-medium text-foreground">
      {children}
    </label>
  );
}

// Map the read-shape UserRoleAssignmentItem[] (with role_name, status,
// nullable org_node_id, etc.) into the write-shape RoleAssignmentRow[]
// the editor consumes. Skip rows with null org_node_id (legacy pre-
// Step-6.14 anchored-at-tenant-root assignments — backend's diff-replace
// will revoke them on save unless the user re-adds explicit anchors;
// documented behaviour, non-blocking for v0).
function readToRows(user: TenantUser): RoleAssignmentRow[] {
  return user.roles
    .filter((r) => r.status === "ACTIVE" && r.org_node_id !== null)
    .map((r) => ({
      role_id: r.role_id,
      org_node_id: r.org_node_id as string,
    }));
}

function rowsEqual(
  a: RoleAssignmentRow[],
  b: RoleAssignmentRow[],
): boolean {
  if (a.length !== b.length) return false;
  // Order-insensitive comparison — backend treats the request roles[]
  // as a set for diff-replace purposes.
  const aKeys = a.map((r) => `${r.role_id}::${r.org_node_id}`).sort();
  const bKeys = b.map((r) => `${r.role_id}::${r.org_node_id}`).sort();
  return aKeys.every((k, i) => k === bKeys[i]);
}

export type EditTenantUserModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  user: TenantUser;
};

export function EditTenantUserModal({
  open,
  onOpenChange,
  user,
}: EditTenantUserModalProps) {
  const mutation = useEditTenantUser();

  const initialName = user.full_name;
  const initialEmail = user.email;
  const initialRoles = readToRows(user);

  const [fullName, setFullName] = useState(initialName);
  const [email, setEmail] = useState(initialEmail);
  const [roles, setRoles] = useState<RoleAssignmentRow[]>(initialRoles);
  const [rolesTouched, setRolesTouched] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [duplicateRowError, setDuplicateRowError] = useState<string | null>(
    null,
  );

  useEffect(() => {
    if (open) {
      setFullName(user.full_name);
      setEmail(user.email);
      setRoles(readToRows(user));
      setRolesTouched(false);
      setFormError(null);
      setDuplicateRowError(null);
    }
  }, [open, user]);

  const incomplete = hasIncompleteRows(roles);
  const duplicateIndexes = findDuplicateIndexes(roles);
  const hasDuplicates = duplicateIndexes.size > 0;

  const nameChanged = fullName.trim() !== initialName;
  const emailChanged = email.trim() !== initialEmail;
  const rolesChanged = rolesTouched && !rowsEqual(roles, initialRoles);
  const hasChanges = nameChanged || emailChanged || rolesChanged;

  const submitDisabled =
    mutation.isPending || !hasChanges || incomplete || hasDuplicates;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    setDuplicateRowError(null);

    if (incomplete) {
      setFormError("Every role assignment needs a role and an anchor.");
      return;
    }
    if (hasDuplicates) {
      setFormError("Resolve duplicate role assignments before saving.");
      return;
    }

    const trimmedName = fullName.trim();
    const trimmedEmail = email.trim();

    if (nameChanged && (trimmedName.length < 1 || trimmedName.length > 200)) {
      setFormError("Full name must be 1-200 chars.");
      return;
    }

    const patch: TenantUserPatchPayload = {};
    if (nameChanged) patch.full_name = trimmedName;
    if (emailChanged) patch.email = trimmedEmail;
    if (rolesChanged) {
      // Roles tri-state: undefined (omitted) = no change, [] = revoke
      // all, [...] = diff-replace. We only include `roles` when the
      // editor's been touched AND the order-insensitive set differs.
      patch.roles = roles as RoleAssignmentItem[];
    }

    try {
      await mutation.mutateAsync({ id: user.id, patch });
      toast.success(`${user.full_name} updated`);
      onOpenChange(false);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "DUPLICATE_ROLE_ASSIGNMENT_IN_REQUEST") {
          setDuplicateRowError(
            "Backend rejected duplicate role assignments. Resolve the highlighted rows and try again.",
          );
          setFormError(null);
          return;
        }
        if (err.code === "EMPTY_PATCH") {
          // Client diff said something changed but the backend
          // disagreed — defensive surface for debugging.
          setFormError(
            "No changes detected by the server. Refresh and try again.",
          );
          return;
        }
        setFormError(err.message);
        if (err.status >= 500) {
          toast.error("Could not update user. Please try again.");
        }
        return;
      }
      toast.error("Could not update user. Please try again.");
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Edit User"
      subtitle={user.email}
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={mutation.isPending}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            form="edit-tenant-user-form"
            disabled={submitDisabled}
          >
            {mutation.isPending ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                Saving…
              </>
            ) : (
              "Save changes"
            )}
          </Button>
        </div>
      }
    >
      <form
        id="edit-tenant-user-form"
        onSubmit={onSubmit}
        className="flex flex-col gap-4"
        noValidate
      >
        {formError ? (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm dark:border-red-500/30 dark:bg-red-500/5"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600 dark:text-red-400" />
            <div>
              <p className="font-medium">Could not update user.</p>
              <p className="text-muted-foreground">{formError}</p>
            </div>
          </div>
        ) : null}

        {duplicateRowError ? (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm dark:border-red-500/30 dark:bg-red-500/5"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600 dark:text-red-400" />
            <p className="text-muted-foreground">{duplicateRowError}</p>
          </div>
        ) : null}

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="full_name">Full name</FieldLabel>
          <Input
            id="full_name"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            maxLength={200}
            className={FIELD_INPUT_CLASS}
          />
        </div>

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="email">Email</FieldLabel>
          <Input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={FIELD_INPUT_CLASS}
          />
          <p className="text-caption text-foreground-muted">
            Server lowercases on save.
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <FieldLabel htmlFor="roles-editor">Role assignments</FieldLabel>
          <p className="text-caption text-foreground-muted">
            Diff-replace: unchanged role/anchor pairs keep their grant
            history. Removing all rows revokes every active assignment.
          </p>
          <RoleAssignmentEditor
            value={roles}
            onChange={(next) => {
              setRoles(next);
              setRolesTouched(true);
            }}
            tenantId={user.tenant_id}
            disabled={mutation.isPending}
          />
        </div>
      </form>
    </Modal>
  );
}
