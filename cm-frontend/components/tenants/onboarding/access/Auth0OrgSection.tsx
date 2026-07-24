"use client";

import { useState } from "react";
import { toast } from "sonner";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Chip } from "@/components/shared/Chips";
import { Skeleton } from "@/components/shared/Skeleton";
import { ApiError } from "@/lib/api/client";
import { useOnboardingState } from "@/lib/hooks/use-onboarding";
import { useProvisionTenantAuth0 } from "@/lib/hooks/use-provisioning";
import type { TenantOrgProvisionResult } from "@/types/api";

export function Auth0OrgSection({ tenantId }: { tenantId: string }) {
  // Durable fact from onboarding-state (backend option a): TRUE once the
  // org id is persisted. Shares the shell's cached query.
  const stateQuery = useOnboardingState(tenantId);
  const provision = useProvisionTenantAuth0(tenantId);
  const [result, setResult] = useState<TenantOrgProvisionResult | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  const provisioned =
    stateQuery.data?.provisioning.auth0_organization === "TRUE";

  async function onProvision() {
    setUnavailable(false);
    try {
      const res = await provision.mutateAsync();
      setResult(res);
      toast.success(
        res.created
          ? "Auth0 organization created"
          : "Auth0 organization already provisioned",
      );
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "PROVISIONING_UNAVAILABLE") {
          setUnavailable(true);
          return;
        }
        toast.error(err.message);
        return;
      }
      toast.error("Could not provision the Auth0 organization.");
    }
  }

  if (stateQuery.isLoading) return <Skeleton variant="card" />;

  return (
    <div className="flex flex-col gap-3 rounded-md border border-border p-4">
      {unavailable ? (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-500/30 dark:bg-amber-500/5"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
          <div>
            <p className="font-medium">Auth0 provisioning is not configured.</p>
            <p className="text-muted-foreground">
              The Auth0 management client is unavailable in this environment;
              provisioning can be run once it is configured.
            </p>
          </div>
        </div>
      ) : null}

      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {provisioned ? (
            <Chip tone="green">
              <CheckCircle2 className="h-3 w-3" /> Provisioned
            </Chip>
          ) : (
            <Chip tone="grey">Not provisioned</Chip>
          )}
        </div>
        <Button
          type="button"
          variant={provisioned ? "outline" : "default"}
          onClick={onProvision}
          disabled={provision.isPending}
        >
          {provision.isPending ? (
            <>
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              Provisioning...
            </>
          ) : provisioned ? (
            "Re-provision"
          ) : (
            "Provision Auth0 organization"
          )}
        </Button>
      </div>

      {result ? (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          <dt className="text-muted-foreground">Org name</dt>
          <dd className="font-mono">{result.org_name}</dd>
          <dt className="text-muted-foreground">Org id</dt>
          <dd className="font-mono">{result.org_id}</dd>
        </dl>
      ) : provisioned ? (
        <p className="text-xs text-muted-foreground">
          Re-provision to view the organization id and name (idempotent).
        </p>
      ) : null}
    </div>
  );
}
