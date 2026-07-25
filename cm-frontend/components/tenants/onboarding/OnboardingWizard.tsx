"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { onboardingApi } from "@/lib/api/onboarding";
import {
  useOnboardingState,
  usePatchOnboardingState,
} from "@/lib/hooks/use-onboarding";
import { useTenant } from "@/lib/hooks/use-tenants";
import type { OnboardingStateResponse } from "@/types/api";

import { StepRail, type RailState } from "./StepRail";
import type { WizardMode } from "./step-props";
import {
  ENABLED_STEP_KEYS,
  isWizardStepKey,
  nextEnabledStep,
  prevEnabledStep,
  WIZARD_STEPS,
  type WizardStepKey,
} from "./wizard-steps";
import { CompanyProfileStep } from "./steps/CompanyProfileStep";
import { LegalStatutoryStep } from "./steps/LegalStatutoryStep";
import { BillingFinanceStep } from "./steps/BillingFinanceStep";
import { ContactsStep } from "./steps/ContactsStep";
import { DocumentsStep } from "./steps/DocumentsStep";
import { AccessUsersStep } from "./steps/AccessUsersStep";
import { ReviewConfirmStep } from "./steps/ReviewConfirmStep";

const TENANTS_URL = "/superadmin/tenants";

function sectionComplete(
  state: OnboardingStateResponse | undefined,
  key: WizardStepKey,
): boolean {
  if (!state) return false;
  const status = (state.section_status ?? {}) as Record<string, unknown>;
  if (status[key] === "complete") return true;
  const p = state.sections_present;
  switch (key) {
    case "legal":
      return p.legal;
    case "billing":
      return p.billing;
    case "contacts":
      return p.contacts;
    // documents is NOT handled here: its rail state is derived by
    // documentsRail (complete only when total >= 1 AND all_verified;
    // warning when visited-but-not-satisfied). stateFor special-cases it.
    default:
      return false;
  }
}

// Documents rail derivation (separate from sectionComplete): the step is
// complete only when at least one document exists and all are verified;
// once the step has been visited (saved through, so section_status.documents
// is marked) but that is not yet true, it shows a warning with a short
// reason; otherwise pending. Fixes the bug where saving the step with zero
// documents marked the rail green.
function documentsRail(
  state: OnboardingStateResponse | undefined,
): { state: RailState; reason: string | null } {
  if (!state) return { state: "pending", reason: null };
  const d = state.sections_present.documents;
  if (d.total >= 1 && d.all_verified) return { state: "complete", reason: null };
  const status = (state.section_status ?? {}) as Record<string, unknown>;
  const visited = status["documents"] === "complete";
  if (!visited) return { state: "pending", reason: null };
  let reason: string;
  if (d.total === 0) reason = "No documents uploaded";
  else if (d.rejected > 0) reason = `${d.rejected} rejected`;
  else reason = `${d.pending_review} pending review`;
  return { state: "warning", reason };
}

// Edit mode drops the Review & confirm step: there is no onboarding to
// complete for a tenant that is already past ONBOARDING. The remaining six
// sections are the standalone edit surfaces.
const EDIT_STEPS = WIZARD_STEPS.filter((s) => s.key !== "review");
const EDIT_STEP_KEYS: readonly WizardStepKey[] = EDIT_STEPS.map((s) => s.key);

export function OnboardingWizard({ tenantId }: { tenantId: string | null }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const isNew = tenantId === null;

  const stateQuery = useOnboardingState(tenantId);
  const patchState = usePatchOnboardingState(tenantId ?? "");
  const tenantQuery = useTenant(tenantId ?? "");

  // Mode is decided by tenant status on load: ONBOARDING (or a brand-new,
  // not-yet-created tenant) uses the linear onboarding wizard; any other
  // status turns the same shell into the edit surface (the retired
  // EditTenantModal's replacement). While the tenant is still loading we
  // hold on "onboarding" but gate the body behind `loading` below so the
  // onboarding chrome never flashes before the mode is known.
  const tenantStatus = tenantQuery.data?.status ?? null;
  const mode: WizardMode =
    isNew || tenantStatus === null || tenantStatus === "ONBOARDING"
      ? "onboarding"
      : "edit";
  const railSteps = mode === "edit" ? EDIT_STEPS : WIZARD_STEPS;

  const [savedLabel, setSavedLabel] = useState<string | null>(null);
  const dirtyRef = useRef(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const pendingNavRef = useRef<(() => void) | null>(null);

  const setDirty = useCallback((d: boolean) => {
    dirtyRef.current = d;
  }, []);

  // Active step. Onboarding: ?step (if valid + enabled) -> server
  // current_step -> company. Edit: ?step (if a valid non-review section) ->
  // company; the server current_step is an onboarding-progress concept and
  // is ignored, and review is not a section here.
  const urlStep = searchParams.get("step");
  const serverStep = stateQuery.data?.current_step ?? null;
  const activeKey: WizardStepKey = useMemo(() => {
    if (isNew) return "company";
    if (mode === "edit") {
      if (isWizardStepKey(urlStep) && EDIT_STEP_KEYS.includes(urlStep)) {
        return urlStep;
      }
      return "company";
    }
    if (isWizardStepKey(urlStep) && ENABLED_STEP_KEYS.includes(urlStep)) {
      return urlStep;
    }
    if (isWizardStepKey(serverStep) && ENABLED_STEP_KEYS.includes(serverStep)) {
      return serverStep;
    }
    return "company";
  }, [isNew, mode, urlStep, serverStep]);

  function navigate(fn: () => void) {
    if (dirtyRef.current) {
      pendingNavRef.current = fn;
      setConfirmOpen(true);
      return;
    }
    fn();
  }

  function goTo(key: WizardStepKey) {
    if (!tenantId) return;
    const sp = new URLSearchParams(searchParams.toString());
    sp.set("step", key);
    dirtyRef.current = false;
    router.replace(`${TENANTS_URL}/onboard/${tenantId}?${sp.toString()}`);
  }

  function exit() {
    router.push(TENANTS_URL);
  }

  // Company create (new-tenant route): after POST, stamp state and jump to
  // the resume route on the legal step.
  async function onCompanyCreated(newId: string) {
    try {
      await onboardingApi.patchState(newId, {
        current_step: "legal",
        section_status: { company: "complete" },
      });
    } catch {
      // Non-fatal: the tenant exists; resume will still land correctly from
      // presence flags. Surface nothing here.
    }
    router.replace(`${TENANTS_URL}/onboard/${newId}?step=legal`);
  }

  // Content-step save. Edit mode: the step already ran its own PUT/PATCH;
  // there is no onboarding progress to stamp and nowhere to advance, so we
  // just confirm and stay put. Onboarding mode: persist current_step +
  // section_status, then advance.
  async function onStepSaved() {
    if (!tenantId) return;
    if (mode === "edit") {
      dirtyRef.current = false;
      toast.success("Changes saved");
      return;
    }
    const next = nextEnabledStep(activeKey);
    const prevStatus = (stateQuery.data?.section_status ?? {}) as Record<string, unknown>;
    try {
      await patchState.mutateAsync({
        current_step: next ?? activeKey,
        section_status: { ...prevStatus, [activeKey]: "complete" },
      });
      setSavedLabel("Draft saved");
    } catch {
      // The section itself already saved; only the resume-state stamp failed.
      toast.error("Saved, but could not update wizard progress. It will re-sync on reload.");
    }
    dirtyRef.current = false;
    if (next) {
      goTo(next);
    }
    // No else: review is the last enabled step and completes via its own
    // Confirm action (onComplete), not the generic step-save advance.
  }

  // Review step confirm success: route to the tenant detail + success toast.
  function onOnboardingComplete(statusLabel: string) {
    dirtyRef.current = false;
    toast.success(
      statusLabel === "TRIAL"
        ? "Onboarding complete. Tenant is now on Trial."
        : `Onboarding complete. Tenant status: ${statusLabel}.`,
    );
    if (tenantId) {
      router.push(`${TENANTS_URL}?tenant=${tenantId}`);
    } else {
      router.push(TENANTS_URL);
    }
  }

  function stateFor(key: WizardStepKey): RailState {
    // Any step not in the enabled set renders disabled (none in v-final,
    // but the guard stays for forward-compat).
    if (!ENABLED_STEP_KEYS.includes(key)) return "disabled";
    if (isNew) {
      // No tenant yet: only company is reachable.
      return key === "company" ? "current" : "disabled";
    }
    if (key === activeKey) return "current";
    // Documents derives from the onboarding-state documents block, not from
    // section_status alone (a saved-but-empty step must not read complete).
    if (key === "documents") return documentsRail(stateQuery.data).state;
    if (sectionComplete(stateQuery.data, key)) return "complete";
    return "pending";
  }

  function reasonFor(key: WizardStepKey): string | null {
    // Only the documents step carries a rail reason, and only when it is
    // the non-active warning state (documentsRail returns a reason there).
    if (isNew || key !== "documents" || key === activeKey) return null;
    return documentsRail(stateQuery.data).reason;
  }

  const onBack = (() => {
    // Edit mode has no linear Back: navigation is purely section-to-section
    // via the rail.
    if (isNew || mode === "edit") return null;
    const prev = prevEnabledStep(activeKey);
    return prev ? () => navigate(() => goTo(prev)) : null;
  })();

  function renderStep() {
    // react-hooks/refs is scoped-off for this block: the callbacks below
    // (onStepSaved / onBack / setDirty) read or write dirtyRef ONLY inside
    // event handlers (step save, rail/back navigation, exit, discard
    // confirm), never during render. dirtyRef is a ref (not state) on
    // purpose: the child steps report dirty from a form-state effect, and a
    // ref avoids the set-state-in-effect churn the codebase deliberately
    // avoids (PATTERNS.md). The lint rule is conservative about passing any
    // ref-touching callback to a child component.
    /* eslint-disable react-hooks/refs */
    if (activeKey === "company") {
      return (
        <CompanyProfileStep
          tenantId={tenantId}
          onCreated={onCompanyCreated}
          onSaved={onStepSaved}
          onBack={onBack}
          setDirty={setDirty}
          mode={mode}
        />
      );
    }
    if (!tenantId) return null;
    const common = { tenantId, onSaved: onStepSaved, onBack, setDirty, mode };
    switch (activeKey) {
      case "legal":
        return <LegalStatutoryStep {...common} />;
      case "billing":
        return <BillingFinanceStep {...common} />;
      case "contacts":
        return <ContactsStep {...common} />;
      case "documents":
        return <DocumentsStep {...common} />;
      case "access":
        return <AccessUsersStep {...common} />;
      case "review":
        return (
          <ReviewConfirmStep
            tenantId={tenantId}
            onEditStep={(key) => navigate(() => goTo(key))}
            onBack={onBack}
            onComplete={onOnboardingComplete}
            setDirty={setDirty}
          />
        );
      default:
        return null;
    }
    /* eslint-enable react-hooks/refs */
  }

  // Gate on the tenant load too: the mode (and therefore all rail/step
  // chrome) depends on tenant status, so the body must wait for it to avoid
  // flashing onboarding chrome for an edit-mode tenant. Onboarding-state is
  // only needed by onboarding mode's rail derivation.
  const loading =
    !isNew &&
    (tenantQuery.isLoading || (mode === "onboarding" && stateQuery.isLoading));
  const errored =
    !isNew &&
    (!!tenantQuery.error || (mode === "onboarding" && !!stateQuery.error));

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold">
            {mode === "edit" ? "Edit client" : "Client onboarding"}
          </h1>
          <p className="text-sm text-muted-foreground">
            {mode === "edit"
              ? tenantQuery.data?.name
                ? `Update ${tenantQuery.data.name}'s details`
                : "Update this client's details"
              : isNew
                ? "Create a new client organization"
                : "Complete the onboarding wizard"}
          </p>
        </div>
        <Button type="button" variant="ghost" size="sm" onClick={() => navigate(exit)}>
          <X className="mr-1 h-4 w-4" /> Exit
        </Button>
      </header>

      <div className="flex min-h-0 flex-1">
        <StepRail
          activeKey={activeKey}
          stateFor={stateFor}
          reasonFor={reasonFor}
          onSelect={(key) => navigate(() => goTo(key))}
          saving={patchState.isPending}
          savedLabel={savedLabel}
          steps={railSteps}
          showProgress={mode === "onboarding"}
        />
        <div className="flex min-h-0 flex-1 flex-col">
          {loading ? (
            <div className="p-6"><Skeleton variant="card" /></div>
          ) : errored ? (
            <div className="p-6">
              <ErrorInline message="Could not load onboarding state." onRetry={() => stateQuery.refetch()} />
            </div>
          ) : (
            renderStep()
          )}
        </div>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Discard unsaved changes?"
        body="This step has unsaved changes. Leaving now will discard them."
        confirmLabel="Discard"
        cancelLabel="Keep editing"
        variant="destructive"
        onConfirm={() => {
          setConfirmOpen(false);
          dirtyRef.current = false;
          const fn = pendingNavRef.current;
          pendingNavRef.current = null;
          fn?.();
        }}
      />
    </div>
  );
}
