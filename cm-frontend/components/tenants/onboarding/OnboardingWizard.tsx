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
import type { OnboardingStateResponse } from "@/types/api";

import { StepRail, type RailState } from "./StepRail";
import {
  ENABLED_STEP_KEYS,
  isWizardStepKey,
  nextEnabledStep,
  prevEnabledStep,
  type WizardStepKey,
} from "./wizard-steps";
import { CompanyProfileStep } from "./steps/CompanyProfileStep";
import { LegalStatutoryStep } from "./steps/LegalStatutoryStep";
import { BillingFinanceStep } from "./steps/BillingFinanceStep";
import { ContactsStep } from "./steps/ContactsStep";
import { DocumentsStep } from "./steps/DocumentsStep";

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
    case "documents":
      return p.documents.total > 0;
    default:
      return false;
  }
}

export function OnboardingWizard({ tenantId }: { tenantId: string | null }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const isNew = tenantId === null;

  const stateQuery = useOnboardingState(tenantId);
  const patchState = usePatchOnboardingState(tenantId ?? "");

  const [savedLabel, setSavedLabel] = useState<string | null>(null);
  const dirtyRef = useRef(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const pendingNavRef = useRef<(() => void) | null>(null);

  const setDirty = useCallback((d: boolean) => {
    dirtyRef.current = d;
  }, []);

  // Active step: ?step (if valid + enabled) -> server current_step -> company.
  const urlStep = searchParams.get("step");
  const serverStep = stateQuery.data?.current_step ?? null;
  const activeKey: WizardStepKey = useMemo(() => {
    if (isNew) return "company";
    if (isWizardStepKey(urlStep) && ENABLED_STEP_KEYS.includes(urlStep)) {
      return urlStep;
    }
    if (isWizardStepKey(serverStep) && ENABLED_STEP_KEYS.includes(serverStep)) {
      return serverStep;
    }
    return "company";
  }, [isNew, urlStep, serverStep]);

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

  // Content-step save: persist current_step + section_status, then advance.
  async function onStepSaved() {
    if (!tenantId) return;
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
    } else {
      toast.message("Access & users and Review & confirm are coming soon.");
    }
  }

  function stateFor(key: WizardStepKey): RailState {
    // access / review: disabled placeholders this slice.
    if (!ENABLED_STEP_KEYS.includes(key)) return "disabled";
    if (isNew) {
      // No tenant yet: only company is reachable.
      return key === "company" ? "current" : "disabled";
    }
    if (key === activeKey) return "current";
    if (sectionComplete(stateQuery.data, key)) return "complete";
    return "pending";
  }

  const onBack = (() => {
    if (isNew) return null;
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
        />
      );
    }
    if (!tenantId) return null;
    const common = { tenantId, onSaved: onStepSaved, onBack, setDirty };
    switch (activeKey) {
      case "legal":
        return <LegalStatutoryStep {...common} />;
      case "billing":
        return <BillingFinanceStep {...common} />;
      case "contacts":
        return <ContactsStep {...common} />;
      case "documents":
        return <DocumentsStep {...common} />;
      default:
        return null;
    }
    /* eslint-enable react-hooks/refs */
  }

  const loading = !isNew && stateQuery.isLoading;
  const errored = !isNew && !!stateQuery.error;

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold">Client onboarding</h1>
          <p className="text-sm text-muted-foreground">
            {isNew ? "Create a new client organization" : "Complete the onboarding wizard"}
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
          onSelect={(key) => navigate(() => goTo(key))}
          saving={patchState.isPending}
          savedLabel={savedLabel}
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
