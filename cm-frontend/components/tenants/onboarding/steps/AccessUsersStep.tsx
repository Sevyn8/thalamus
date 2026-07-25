"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { useTenant } from "@/lib/hooks/use-tenants";
import { StepShell } from "@/components/tenants/onboarding/StepShell";
import { ModuleAccessSection } from "@/components/tenants/onboarding/access/ModuleAccessSection";
import { Auth0OrgSection } from "@/components/tenants/onboarding/access/Auth0OrgSection";
import { AdminUsersSection } from "@/components/tenants/onboarding/access/AdminUsersSection";
import type { StepProps } from "@/components/tenants/onboarding/step-props";

// Step 6: Access & users. Three sub-sections, each committing its actions
// immediately (module toggles, provision, create/provision/invite), so
// there is no unsaved wizard-form state — navigation away is always safe.
export function AccessUsersStep({ tenantId, onSaved, onBack, setDirty, mode }: StepProps) {
  const tenant = useTenant(tenantId);

  useEffect(() => setDirty(false), [setDirty]);

  // Every action in this step (module toggles, Auth0 org provisioning,
  // user invites) persists immediately, so edit mode has nothing to "save
  // and continue" to: drop the footer bar entirely. Onboarding mode keeps
  // the Save & continue advance.
  return (
    <StepShell
      title="Access & users"
      description="Grant modules, provision the tenant's Auth0 organization, and invite its admin users."
      footer={
        mode === "edit" ? undefined : (
          <div className="flex items-center justify-between border-t border-border px-6 py-4">
            <div>
              {onBack ? (
                <Button type="button" variant="outline" onClick={onBack}>Back</Button>
              ) : null}
            </div>
            <Button type="button" onClick={onSaved}>Save & continue</Button>
          </div>
        )
      }
    >
      <div className="flex flex-col gap-8">
        <section className="flex flex-col gap-3">
          <div>
            <h3 className="text-sm font-medium">Module access</h3>
            <p className="text-xs text-muted-foreground">
              Modules this tenant can use. Changes apply immediately.
            </p>
          </div>
          <ModuleAccessSection tenantId={tenantId} tenantName={tenant.data?.name} />
        </section>

        <section className="flex flex-col gap-3">
          <div>
            <h3 className="text-sm font-medium">Auth0 organization</h3>
            <p className="text-xs text-muted-foreground">
              The tenant&apos;s identity boundary in Auth0. Provisioning is idempotent.
            </p>
          </div>
          <Auth0OrgSection tenantId={tenantId} />
        </section>

        <AdminUsersSection tenantId={tenantId} />
      </div>
    </StepShell>
  );
}
