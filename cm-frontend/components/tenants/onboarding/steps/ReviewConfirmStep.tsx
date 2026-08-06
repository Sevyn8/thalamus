"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, CheckCircle2, Loader2, Pencil } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Chip } from "@/components/shared/Chips";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { ApiError } from "@/lib/api/client";
import { useTenant } from "@/lib/hooks/use-tenants";
import {
  useBillingProfile,
  useCompleteOnboarding,
  useContacts,
  useLegalProfile,
  useOnboardingState,
  useTaxRegistrations,
} from "@/lib/hooks/use-onboarding";
import { useDocuments } from "@/lib/hooks/use-documents";
import { useTenantUsers } from "@/lib/hooks/use-tenant-users";
import { StepShell } from "@/components/tenants/onboarding/StepShell";
import type { WizardStepKey } from "@/components/tenants/onboarding/wizard-steps";
import type { OnboardingStateResponse } from "@/types/api";

export type ReviewConfirmStepProps = {
  tenantId: string;
  onEditStep: (key: WizardStepKey) => void;
  onBack: (() => void) | null;
  onComplete: (statusLabel: string) => void;
  setDirty: (dirty: boolean) => void;
};

type Row = {
  key: WizardStepKey;
  label: string;
  ok: boolean;
  facts: string;
};

export function ReviewConfirmStep({
  tenantId,
  onEditStep,
  onBack,
  onComplete,
  setDirty,
}: ReviewConfirmStepProps) {
  const stateQuery = useOnboardingState(tenantId);
  const tenant = useTenant(tenantId);
  const legal = useLegalProfile(tenantId);
  const tax = useTaxRegistrations(tenantId);
  const billing = useBillingProfile(tenantId);
  const contacts = useContacts(tenantId);
  const documents = useDocuments(tenantId);
  const users = useTenantUsers({ tenant_id: tenantId });
  const complete = useCompleteOnboarding(tenantId);
  // Item 4: once Confirm is clicked we stay disabled through navigation.
  // complete.isPending flips back to false when the mutation resolves,
  // BEFORE the async router.push completes, which briefly re-enabled the
  // button and allowed a second click (-> a spurious 409). `completing`
  // is set on click and only cleared on error, so a successful confirm
  // keeps the button disabled until the component unmounts on navigation.
  const [completing, setCompleting] = useState(false);

  // Review commits nothing until Confirm; navigation away is always safe.
  useEffect(() => setDirty(false), [setDirty]);

  const loading =
    stateQuery.isLoading ||
    tenant.isLoading ||
    legal.isLoading ||
    billing.isLoading ||
    contacts.isLoading ||
    documents.isLoading ||
    users.isLoading;

  if (loading) {
    return <StepShell title="Review & confirm"><Skeleton variant="card" /></StepShell>;
  }
  if (stateQuery.error || !stateQuery.data) {
    return (
      <StepShell title="Review & confirm">
        <ErrorInline
          message="Could not load the onboarding summary."
          onRetry={() => stateQuery.refetch()}
        />
      </StepShell>
    );
  }

  const state: OnboardingStateResponse = stateQuery.data;
  const present = state.sections_present;
  const prov = state.provisioning;

  const contactCount = contacts.data?.items.length ?? 0;
  const taxCount = tax.data?.items.length ?? 0;
  const invitedCount = (users.data?.items ?? []).filter(
    (u) => u.invited_at !== null || u.invitation_accepted_at !== null,
  ).length;
  const docs = present.documents;

  // Per-section summary rows. ok drives the tick vs warning; facts is the
  // one-line summary. Company has no presence flag (the tenant exists), so
  // it is always ok once we are here.
  const rows: Row[] = [
    {
      key: "company",
      label: "Company profile",
      ok: true,
      facts: tenant.data
        ? `${tenant.data.name} · ${tenant.data.region}${tenant.data.tier ? ` · ${tenant.data.tier}` : ""}`
        : "-",
    },
    {
      key: "legal",
      label: "Legal & statutory",
      ok: present.legal,
      facts: legal.data
        ? `${legal.data.legal_entity_name} · ${legal.data.entity_type}` +
          (taxCount > 0 ? ` · ${taxCount} tax registration(s)` : "")
        : "Legal profile not saved",
    },
    {
      key: "billing",
      label: "Billing & finance",
      ok: present.billing,
      facts: billing.data
        ? [billing.data.payment_terms, billing.data.currency]
            .filter(Boolean)
            .join(" · ") || "Saved"
        : "Billing profile not saved",
    },
    {
      key: "contacts",
      label: "Contacts",
      ok: present.contacts,
      facts:
        contactCount > 0
          ? `${contactCount} contact(s)`
          : "No contacts added",
    },
    {
      key: "documents",
      label: "Documents",
      ok: docs.all_verified,
      facts: `${docs.total} total · ${docs.verified} verified · ${docs.pending_review} pending · ${docs.rejected} rejected`,
    },
    {
      key: "access",
      label: "Access & users",
      ok: prov.auth0_organization === "TRUE" && invitedCount >= 1,
      facts:
        `Auth0 org ${prov.auth0_organization === "TRUE" ? "provisioned" : "not provisioned"}` +
        ` · ${invitedCount} invited admin(s)`,
    },
  ];

  // Client gate mirrors the backend complete-onboarding gate exactly
  // (Slice 6 option a): legal + billing + contact + Auth0 org + >=1 invited
  // admin + documents all-verified.
  const blockers: string[] = [];
  if (!present.legal) blockers.push("legal_profile");
  if (!present.billing) blockers.push("billing_profile");
  if (!present.contacts) blockers.push("contacts");
  if (prov.auth0_organization !== "TRUE") blockers.push("auth0_organization");
  if (invitedCount < 1) blockers.push("admin_invited");
  if (!docs.all_verified) blockers.push("documents");
  const canConfirm = blockers.length === 0;

  async function onConfirm() {
    if (completing) return; // idempotent against double-click
    setCompleting(true);
    try {
      const result = await complete.mutateAsync();
      // Leave `completing` true: onComplete navigates away, and keeping the
      // button disabled until unmount prevents a second submit.
      onComplete(result.status);
    } catch (err) {
      setCompleting(false); // allow retry
      if (err instanceof ApiError) {
        // Item 3: a status change between load and click -> the backend
        // 409 INVALID_STATE_TRANSITION surfaces as a clear message, not a
        // generic toast.
        if (err.code === "INVALID_STATE_TRANSITION") {
          toast.error(
            "Onboarding has already been completed for this tenant.",
          );
          return;
        }
        // Other gate 409s (ONBOARDING_INCOMPLETE) keep their named message.
        toast.error(err.message);
        return;
      }
      toast.error("Could not complete onboarding. Please try again.");
    }
  }

  return (
    <StepShell
      title="Review & confirm"
      description="Confirm the client is ready to go live. Completing onboarding moves the tenant to Trial."
      footer={
        <div className="flex items-center justify-between border-t border-border px-6 py-4">
          <div>
            {onBack ? (
              <Button type="button" variant="outline" onClick={onBack}>Back</Button>
            ) : null}
          </div>
          <Button type="button" onClick={onConfirm} disabled={!canConfirm || completing}>
            {completing ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                Completing...
              </>
            ) : (
              "Confirm & complete onboarding"
            )}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-6">
        {!canConfirm ? (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-[var(--warning-line)] bg-[var(--warning-bg)] p-3 text-sm dark:bg-warning/5"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <div>
              <p className="font-medium">Onboarding is not ready to complete.</p>
              <p className="text-muted-foreground">
                Resolve the flagged sections below. Missing:{" "}
                {blockers.join(", ")}.
              </p>
            </div>
          </div>
        ) : null}

        <ul className="flex flex-col divide-y divide-border rounded-md border border-border">
          {rows.map((row) => (
            <li key={row.key} className="flex items-center gap-3 px-4 py-3">
              <span aria-hidden="true" className="shrink-0">
                {row.ok ? (
                  <CheckCircle2 className="h-5 w-5 text-success" />
                ) : (
                  <AlertTriangle className="h-5 w-5 text-warning" />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{row.label}</div>
                <p className="truncate text-xs text-muted-foreground">{row.facts}</p>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => onEditStep(row.key)}
              >
                <Pencil className="mr-1 h-3.5 w-3.5" /> Edit
              </Button>
            </li>
          ))}
        </ul>

        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-medium">Provisioning checks</h3>
          <div className="flex flex-wrap gap-2">
            <Chip tone={prov.auth0_organization === "TRUE" ? "green" : "grey"}>
              Auth0 org: {prov.auth0_organization}
            </Chip>
            <Chip tone={prov.admin_invited === "TRUE" ? "green" : "grey"}>
              Admin invited: {prov.admin_invited}
            </Chip>
            <Chip tone={docs.all_verified ? "green" : "amber"}>
              Documents: {docs.verified}/{docs.total} verified
            </Chip>
          </div>
        </div>
      </div>
    </StepShell>
  );
}
