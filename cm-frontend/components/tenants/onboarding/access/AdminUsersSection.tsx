"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Loader2, Plus, UserPlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Chip, type Tone } from "@/components/shared/Chips";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { EmptyState } from "@/components/shared/EmptyState";
import { ApiError } from "@/lib/api/client";
import { useTenantUsers, useCreateTenantUser } from "@/lib/hooks/use-tenant-users";
import {
  useProvisionTenantUserAuth0,
  useSendInvitation,
} from "@/lib/hooks/use-provisioning";
import { useOrgTree } from "@/lib/hooks/use-org-nodes";
import { useRoles } from "@/lib/hooks/use-roles";
import type { TenantUser } from "@/types/api";
import {
  FieldError,
  FieldLabel,
  SELECT_CLASS,
} from "@/components/tenants/onboarding/fields";

// Per-user onboarding stage, derived from server fields ONLY (resumable).
// PROVISIONED is intentionally absent: provision-auth0 writes nothing to CM
// (auth0_sub stays NULL until accept), so it is not distinguishable from NEW
// at rest. The sequence handles this by (idempotently) re-provisioning before
// every invite, which also makes the 409 USER_NOT_PROVISIONED unreachable.
type Stage = "NEW" | "INVITED" | "ACCEPTED" | "SUSPENDED";

function deriveStage(u: TenantUser): Stage {
  if (u.invitation_accepted_at !== null || u.status === "ACTIVE") return "ACCEPTED";
  if (u.status === "SUSPENDED") return "SUSPENDED";
  if (u.invited_at !== null) return "INVITED";
  return "NEW";
}

const STAGE_TONE: Record<Stage, Tone> = {
  NEW: "grey",
  INVITED: "blue",
  ACCEPTED: "green",
  SUSPENDED: "red",
};
const STAGE_LABEL: Record<Stage, string> = {
  NEW: "Created",
  INVITED: "Invited",
  ACCEPTED: "Accepted",
  SUSPENDED: "Suspended",
};

// Transient in-flight label for the live sequence (not persisted; resume
// derives from server via deriveStage).
type Busy = "provisioning" | "inviting";

export function AdminUsersSection({ tenantId }: { tenantId: string }) {
  const usersQuery = useTenantUsers({ tenant_id: tenantId });
  const orgTree = useOrgTree(tenantId);
  const roles = useRoles();
  const createUser = useCreateTenantUser();
  const provisionUser = useProvisionTenantUserAuth0();
  const sendInvite = useSendInvitation();

  const [showAdd, setShowAdd] = useState(false);
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [roleId, setRoleId] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<string, Busy>>({});

  const tenantRootId = orgTree.data?.tenant_root_id ?? null;
  const tenantRoles = roles.data?.tenant_roles.items ?? [];

  function resetForm() {
    setEmail("");
    setFullName("");
    setRoleId("");
    setFormError(null);
    setShowAdd(false);
  }

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) {
      setFormError("Enter a valid email address.");
      return;
    }
    if (!fullName.trim()) {
      setFormError("Full name is required.");
      return;
    }
    if (!roleId) {
      setFormError("Select a role.");
      return;
    }
    if (!tenantRootId) {
      setFormError("Tenant org tree is still loading; try again in a moment.");
      return;
    }
    try {
      await createUser.mutateAsync({
        tenant_id: tenantId,
        email: email.trim().toLowerCase(),
        full_name: fullName.trim(),
        roles: [{ role_id: roleId, org_node_id: tenantRootId }],
      });
      toast.success("Admin user created");
      resetForm();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "DUPLICATE_TENANT_USER_EMAIL") {
          setFormError("A user with this email already exists for this tenant.");
          return;
        }
        if (err.code === "INVALID_ROLE" || err.code === "INVALID_ROLE_AUDIENCE") {
          setFormError(err.message);
          return;
        }
        if (err.status >= 500) {
          toast.error("Could not create the user. Please try again.");
          return;
        }
        setFormError(err.message);
        return;
      }
      toast.error("Could not create the user. Please try again.");
    }
  }

  async function runProvisionAndInvite(user: TenantUser) {
    setBusy((b) => ({ ...b, [user.id]: "provisioning" }));
    try {
      // Provision first (idempotent) -> makes the 409 USER_NOT_PROVISIONED
      // precondition unreachable through this UI.
      await provisionUser.mutateAsync(user.id);
      setBusy((b) => ({ ...b, [user.id]: "inviting" }));
      await sendInvite.mutateAsync(user.id);
      toast.success(`Invitation sent to ${user.email}`);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "PROVISIONING_UNAVAILABLE") {
          toast.error(
            "Auth0 provisioning is not configured in this environment.",
          );
        } else if (err.code === "USER_NOT_PROVISIONED") {
          // Should be unreachable (we provision first); surfaced cleanly.
          toast.error(
            "The user is not provisioned in Auth0 yet. Try again.",
          );
        } else {
          toast.error(err.message);
        }
      } else {
        toast.error("Could not complete the invitation. Please try again.");
      }
    } finally {
      setBusy((b) => {
        const next = { ...b };
        delete next[user.id];
        return next;
      });
    }
  }

  const users = usersQuery.data?.items ?? [];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">Admin users</h3>
        <Button type="button" variant="outline" size="sm" onClick={() => setShowAdd((s) => !s)}>
          <Plus className="mr-1 h-3.5 w-3.5" /> Add admin user
        </Button>
      </div>

      {showAdd ? (
        <form onSubmit={onCreate} className="flex flex-col gap-3 rounded-md border border-border p-4" noValidate>
          {formError ? (
            <p className="text-xs text-red-600 dark:text-red-400">{formError}</p>
          ) : null}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <FieldLabel htmlFor="au-email" required>Email</FieldLabel>
              <Input id="au-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="admin@acme.example.com" />
            </div>
            <div className="flex flex-col gap-1">
              <FieldLabel htmlFor="au-name" required>Full name</FieldLabel>
              <Input id="au-name" value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Jane Smith" />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="au-role" required>Role</FieldLabel>
            <select id="au-role" className={SELECT_CLASS} value={roleId} onChange={(e) => setRoleId(e.target.value)}>
              <option value="">Select...</option>
              {tenantRoles.map((r) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </select>
            {roles.error ? <FieldError message="Could not load roles." /> : null}
          </div>
          <div className="flex items-center justify-end gap-2">
            <Button type="button" variant="outline" size="sm" onClick={resetForm} disabled={createUser.isPending}>
              Cancel
            </Button>
            <Button type="submit" size="sm" disabled={createUser.isPending || !tenantRootId}>
              {createUser.isPending ? (
                <><Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> Creating...</>
              ) : (
                <><UserPlus className="mr-1 h-3.5 w-3.5" /> Create user</>
              )}
            </Button>
          </div>
        </form>
      ) : null}

      {usersQuery.isLoading ? (
        <Skeleton variant="card" />
      ) : usersQuery.error ? (
        <ErrorInline message="Could not load users." onRetry={() => usersQuery.refetch()} />
      ) : users.length === 0 ? (
        <EmptyState title="No admin users yet" body="Add the tenant's first admin user above." />
      ) : (
        <ul className="flex flex-col divide-y divide-border rounded-md border border-border">
          {users.map((u) => {
            const stage = deriveStage(u);
            const b = busy[u.id];
            return (
              <li key={u.id} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium">{u.full_name}</span>
                    {b ? (
                      <Chip tone="amber">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        {b === "provisioning" ? "Provisioning" : "Inviting"}
                      </Chip>
                    ) : (
                      <Chip tone={STAGE_TONE[stage]}>{STAGE_LABEL[stage]}</Chip>
                    )}
                  </div>
                  <p className="truncate text-xs text-muted-foreground">
                    {u.email}
                    {stage === "INVITED" && u.invited_at
                      ? ` · invited ${new Date(u.invited_at).toLocaleDateString()}`
                      : ""}
                  </p>
                </div>
                <div className="shrink-0">
                  {stage === "NEW" ? (
                    <Button type="button" size="sm" disabled={!!b} onClick={() => runProvisionAndInvite(u)}>
                      Provision & send invite
                    </Button>
                  ) : stage === "INVITED" ? (
                    <Button type="button" size="sm" variant="outline" disabled={!!b} onClick={() => runProvisionAndInvite(u)}>
                      Resend invite
                    </Button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
