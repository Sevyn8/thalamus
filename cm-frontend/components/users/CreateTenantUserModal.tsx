"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
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
import { useCreateTenantUser } from "@/lib/hooks/use-tenant-users";
import { useTenants } from "@/lib/hooks/use-tenants";
import { ApiError } from "@/lib/api/client";
import type {
  RoleAssignmentItem,
  TenantUserCreatePayload,
} from "@/lib/api/tenant-users";
import { cn } from "@/lib/utils";

const FIELD_INPUT_CLASS = cn(
  "h-9 w-full rounded-md border border-input bg-background px-2.5 py-1 text-sm",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
  "dark:bg-input/30",
);

const SELECT_CLASS = cn(FIELD_INPUT_CLASS, "appearance-none");

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

// Loose RFC-5322 subset matching backend EmailStr's permissive parsing.
// Real validation happens server-side; this just keeps obvious typos
// from being submitted.
function looksLikeEmail(s: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s);
}

export type CreateTenantUserModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // When set, the tenant picker is hidden and the modal targets this
  // tenant directly. Used by drawer-launched flows; the users page
  // launches without preselection so the modal shows the picker.
  preselectedTenantId?: string;
};

export function CreateTenantUserModal({
  open,
  onOpenChange,
  preselectedTenantId,
}: CreateTenantUserModalProps) {
  const router = useRouter();
  const mutation = useCreateTenantUser();
  const tenantsQuery = useTenants();
  const tenants = tenantsQuery.data?.items ?? [];

  const [tenantId, setTenantId] = useState(preselectedTenantId ?? "");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [roles, setRoles] = useState<RoleAssignmentRow[]>([]);
  const [formError, setFormError] = useState<string | null>(null);
  const [duplicateRowError, setDuplicateRowError] = useState<string | null>(
    null,
  );

  useEffect(() => {
    if (open) {
      setTenantId(preselectedTenantId ?? "");
      setFullName("");
      setEmail("");
      setRoles([]);
      setFormError(null);
      setDuplicateRowError(null);
    }
  }, [open, preselectedTenantId]);

  const incomplete = hasIncompleteRows(roles);
  const duplicateIndexes = findDuplicateIndexes(roles);
  const hasDuplicates = duplicateIndexes.size > 0;

  const emailValid = email.length === 0 || looksLikeEmail(email);
  const trimmedName = fullName.trim();
  const formReady =
    !!tenantId &&
    trimmedName.length >= 1 &&
    trimmedName.length <= 200 &&
    looksLikeEmail(email) &&
    roles.length >= 1 &&
    !incomplete &&
    !hasDuplicates;

  const submitDisabled = mutation.isPending || !formReady;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    setDuplicateRowError(null);

    if (!tenantId) {
      setFormError("Pick a tenant.");
      return;
    }
    if (trimmedName.length < 1 || trimmedName.length > 200) {
      setFormError("Full name must be 1-200 chars.");
      return;
    }
    if (!looksLikeEmail(email)) {
      setFormError("Email looks invalid.");
      return;
    }
    if (roles.length < 1) {
      setFormError("At least one role assignment is required.");
      return;
    }
    if (incomplete) {
      setFormError("Every role assignment needs a role and an anchor.");
      return;
    }
    if (hasDuplicates) {
      setFormError("Resolve duplicate role assignments before saving.");
      return;
    }

    const payload: TenantUserCreatePayload = {
      tenant_id: tenantId,
      email: email.trim(),
      full_name: trimmedName,
      roles: roles as RoleAssignmentItem[],
    };

    try {
      const created = await mutation.mutateAsync(payload);
      toast.success(`${created.full_name} invited`);
      onOpenChange(false);
      // Auto-navigate to the new user's drawer so the operator can
      // verify the freshly-provisioned row immediately. Matches the
      // 5n.8a pattern (ProvisionTenantModal restored auto-nav after
      // Sanjeev's Step 6.20.1 lifted the detail-404 blocker; same
      // logic applies here — backend returns the new row on POST).
      const sp = new URLSearchParams();
      sp.set("audience", "tenant");
      sp.set("user", created.id);
      router.push(`/superadmin/users?${sp.toString()}`);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "DUPLICATE_ROLE_ASSIGNMENT_IN_REQUEST") {
          setDuplicateRowError(
            "Backend rejected duplicate role assignments. Resolve the highlighted rows and try again.",
          );
          return;
        }
        setFormError(err.message);
        if (err.status >= 500) {
          toast.error("Could not invite user. Please try again.");
        }
        return;
      }
      toast.error("Could not invite user. Please try again.");
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Invite User"
      subtitle="The user receives an invitation email and joins as INVITED until they accept."
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
            form="create-tenant-user-form"
            disabled={submitDisabled}
          >
            {mutation.isPending ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                Inviting…
              </>
            ) : (
              "Invite user"
            )}
          </Button>
        </div>
      }
    >
      <form
        id="create-tenant-user-form"
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
              <p className="font-medium">Could not invite user.</p>
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

        {preselectedTenantId ? null : (
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="tenant_id" required>
              Tenant
            </FieldLabel>
            <select
              id="tenant_id"
              className={SELECT_CLASS}
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
            >
              <option value="">Select a tenant…</option>
              {tenants.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="full_name" required>
            Full name
          </FieldLabel>
          <Input
            id="full_name"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            maxLength={200}
            placeholder="Jane Doe"
          />
        </div>

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="email" required>
            Email
          </FieldLabel>
          <Input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="jane@example.com"
            aria-invalid={!emailValid}
          />
          <p className="text-caption text-foreground-muted">
            Lowercased server-side. Must be unique within the tenant.
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <FieldLabel htmlFor="roles-editor" required>
            Role assignments
          </FieldLabel>
          {tenantId ? (
            <>
              <p className="text-caption text-foreground-muted">
                At least one role + anchor pair is required.
              </p>
              <RoleAssignmentEditor
                value={roles}
                onChange={setRoles}
                tenantId={tenantId}
                disabled={mutation.isPending}
              />
            </>
          ) : (
            <p className="rounded-md border border-border bg-surface/40 p-3 text-caption text-foreground-muted">
              Pick a tenant above to choose roles and anchors.
            </p>
          )}
        </div>
      </form>
    </Modal>
  );
}
