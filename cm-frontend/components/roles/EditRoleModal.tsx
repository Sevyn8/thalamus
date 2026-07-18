"use client";

import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { AlertCircle, Loader2 } from "lucide-react";

import { Modal } from "@/components/shared/Modal";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ActionChip, ScopeChip } from "@/components/shared/Chips";
import { useRoleDetail, useUpdateRole } from "@/lib/hooks/use-roles";
import { ApiError } from "@/lib/api/client";
import type {
  PermissionDetail,
  RoleDetail,
  RoleUpdateRequest,
} from "@/lib/api/roles";
import { cn } from "@/lib/utils";

const FIELD_INPUT_CLASS = cn(
  "h-9 w-full rounded-md border border-input bg-background px-2.5 py-1 text-sm",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
  "dark:bg-input/30",
);

const TEXTAREA_CLASS = cn(
  "w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-sm",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
  "dark:bg-input/30",
);

function FieldLabel({
  htmlFor,
  children,
  required,
}: {
  htmlFor: string;
  children: React.ReactNode;
  required?: boolean;
}) {
  return (
    <label htmlFor={htmlFor} className="text-xs font-medium text-foreground">
      {children}
      {required ? (
        <span className="ml-0.5 text-red-600 dark:text-red-400">*</span>
      ) : null}
    </label>
  );
}

function setsEqual(a: Set<string>, b: Set<string>): boolean {
  if (a.size !== b.size) return false;
  for (const v of a) if (!b.has(v)) return false;
  return true;
}

// Group permissions by module preserving server-provided sort order
// (module/resource/action/scope ascending per backend LD3).
function groupByModule(
  perms: PermissionDetail[],
): Array<{ module: string; moduleLabel: string; items: PermissionDetail[] }> {
  const groups: Array<{
    module: string;
    moduleLabel: string;
    items: PermissionDetail[];
  }> = [];
  for (const p of perms) {
    const last = groups[groups.length - 1];
    if (last && last.module === p.module) {
      last.items.push(p);
    } else {
      groups.push({
        module: p.module,
        moduleLabel: p.module_label,
        items: [p],
      });
    }
  }
  return groups;
}

export type EditRoleModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  roleId: string;
};

export function EditRoleModal({
  open,
  onOpenChange,
  roleId,
}: EditRoleModalProps) {
  const detailQuery = useRoleDetail(roleId);
  const role = detailQuery.data ?? null;

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Edit Role"
      subtitle={role?.name}
    >
      {detailQuery.isLoading ? (
        <div className="flex flex-col gap-3">
          <Skeleton variant="rect" />
          <Skeleton variant="row" count={8} />
        </div>
      ) : detailQuery.error ? (
        <ErrorInline
          message="Could not load role detail."
          onRetry={() => detailQuery.refetch()}
        />
      ) : role ? (
        <EditRoleForm
          role={role}
          onClose={() => onOpenChange(false)}
        />
      ) : null}
    </Modal>
  );
}

function EditRoleForm({
  role,
  onClose,
}: {
  role: RoleDetail;
  onClose: () => void;
}) {
  const mutation = useUpdateRole();

  const initialName = role.name;
  const initialDescription = role.description;
  const initialPermissionIds = useMemo(
    () => new Set(role.permissions.map((p) => p.id)),
    [role.permissions],
  );

  const [name, setName] = useState(initialName);
  const [description, setDescription] = useState(initialDescription ?? "");
  const [permissionIds, setPermissionIds] = useState<Set<string>>(
    () => new Set(initialPermissionIds),
  );
  const [formError, setFormError] = useState<string | null>(null);

  // Reset when the underlying role changes (e.g. modal re-opens for
  // a different role, or detail refetches after invalidation).
  useEffect(() => {
    setName(role.name);
    setDescription(role.description ?? "");
    setPermissionIds(new Set(role.permissions.map((p) => p.id)));
    setFormError(null);
  }, [role.id, role.name, role.description, role.permissions]);

  // The full picker shows both currently-granted and grantable. The
  // server pre-filters `available_permissions` to exclude GLOBAL-scope
  // rows for TENANT-audience roles per LD2 — combining held + available
  // gives the union of what *this* role can ever hold.
  const allPermissions = useMemo(
    () => [...role.permissions, ...role.available_permissions],
    [role.permissions, role.available_permissions],
  );
  const groups = useMemo(() => groupByModule(allPermissions), [allPermissions]);

  const nameTrimmed = name.trim();
  const descTrimmed = description.trim();
  const nameChanged = nameTrimmed !== initialName;
  // description nullable: empty string in the textarea maps to null on
  // submit (intent: "no description") — only emit a change if the
  // null/string boundary or the trimmed value actually moved.
  const descNext: string | null = descTrimmed === "" ? null : descTrimmed;
  const descChanged = descNext !== (initialDescription ?? null);
  const permsChanged = !setsEqual(permissionIds, initialPermissionIds);
  const hasChanges = nameChanged || descChanged || permsChanged;

  const nameValid = nameTrimmed.length >= 1 && nameTrimmed.length <= 100;
  const submitDisabled = mutation.isPending || !hasChanges || !nameValid;

  function togglePermission(id: string) {
    setPermissionIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);

    if (!nameValid) {
      setFormError("Role name must be 1-100 characters.");
      return;
    }

    const patch: RoleUpdateRequest = {};
    if (nameChanged) patch.name = nameTrimmed;
    if (descChanged) patch.description = descNext;
    if (permsChanged) patch.permission_ids = Array.from(permissionIds);

    try {
      await mutation.mutateAsync({ id: role.id, patch });
      toast.success(`${role.name} updated`);
      onClose();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "LAST_OVERRIDE_HOLDER") {
          setFormError(
            "Cannot remove this permission — it would leave the system without any holder of an OVERRIDE-scope grant.",
          );
          return;
        }
        if (err.code === "SUPER_ADMIN_PROTECTED") {
          setFormError(
            "SUPER_ADMIN role permissions cannot be modified.",
          );
          return;
        }
        if (err.code === "AUDIENCE_SCOPE_MISMATCH") {
          setFormError(
            "One or more selected permissions don't match this role's audience scope.",
          );
          return;
        }
        if (err.code === "INVALID_PERMISSION_ID") {
          setFormError(
            "One or more selected permissions are not in the catalogue. Refresh and retry.",
          );
          return;
        }
        if (err.code === "EMPTY_PATCH") {
          setFormError("No changes detected by the server. Refresh and try again.");
          return;
        }
        setFormError(err.message);
        if (err.status >= 500) {
          toast.error("Could not update role. Please try again.");
        }
        return;
      }
      toast.error("Could not update role. Please try again.");
    }
  }

  return (
    <form
      id="edit-role-form"
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
            <p className="font-medium">Could not update role.</p>
            <p className="text-muted-foreground">{formError}</p>
          </div>
        </div>
      ) : null}

      <div className="flex flex-col gap-1">
        <FieldLabel htmlFor="role-name" required>
          Name
        </FieldLabel>
        <Input
          id="role-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={100}
          className={FIELD_INPUT_CLASS}
        />
      </div>

      <div className="flex flex-col gap-1">
        <FieldLabel htmlFor="role-description">Description</FieldLabel>
        <textarea
          id="role-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          className={TEXTAREA_CLASS}
        />
      </div>

      <div className="flex flex-col gap-2">
        <FieldLabel htmlFor="role-permissions">Permissions</FieldLabel>
        <p className="text-caption text-foreground-muted">
          Replace-set: the saved list is exactly what's checked. Unchanged
          rows preserve their audit history.
        </p>
        <div
          id="role-permissions"
          className="max-h-80 overflow-auto rounded-md border border-border"
        >
          {groups.length === 0 ? (
            <p className="p-3 text-sm text-muted-foreground">
              No permissions available for this role.
            </p>
          ) : (
            groups.map((g) => (
              <div key={g.module} className="border-b border-border last:border-b-0">
                <div className="bg-muted/40 px-3 py-1.5 text-label text-muted-foreground">
                  {g.moduleLabel}
                </div>
                <ul>
                  {g.items.map((p) => {
                    const checked = permissionIds.has(p.id);
                    return (
                      <li key={p.id}>
                        <label className="flex cursor-pointer items-center gap-3 px-3 py-1.5 text-sm hover:bg-accent/40">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => togglePermission(p.id)}
                            className="h-3.5 w-3.5"
                          />
                          <span className="min-w-0 flex-1">
                            <span className="font-medium">{p.resource_label}</span>
                          </span>
                          <ActionChip action={p.action} />
                          <ScopeChip scope={p.scope} />
                        </label>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="flex items-center justify-end gap-2 pt-2">
        <Button
          type="button"
          variant="outline"
          onClick={onClose}
          disabled={mutation.isPending}
        >
          Cancel
        </Button>
        <Button type="submit" disabled={submitDisabled}>
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
    </form>
  );
}
