"use client";

import type { ReactNode } from "react";
import { Check, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { cn } from "@/lib/utils";

// Phase 5c.8f1: lifted at third-consumer arrival (CreateSourceWizard
// from 5c.2b1 + ProvisioningWizard from 5c.8d2 + Onboarding wizard
// from this chunk). Per the explicit deferral in 5c.8d2's closeout:
// "Lift if a third wizard arrives." That arrival is now.
//
// Encapsulates: step-indicator markup, "Step X of N: <label>"
// caption, content-panel wrapper, Cancel / Back / Next / Submit
// footer. Per-wizard state machine + step-content rendering stay
// in callers — those are the heavy / wizard-specific volume.
//
// DOM structure preserves the shape of the inline scaffolds it
// replaces so existing role-based e2e selectors continue to work
// without changes (ol[aria-label="Wizard progress"], button names,
// Cancel/Back/Next/Save).
//
// Cancel UX is a single onCancel callback. Callers that want a
// discard-draft confirmation (e.g., ProvisioningWizard) wrap their
// own AlertDialog around the callback — chrome stays simple.

export type WizardChromeProps = {
  // Step labels in order; length defines the step count.
  stepLabels: string[];
  // 1-indexed current step.
  currentStep: number;
  // Whether the Next / Submit button is enabled (callers compute
  // from per-step canAdvance logic).
  canAdvance: boolean;
  // Submit pending state — drives "Saving…" button label.
  isPending?: boolean;
  // Custom submit-button labels.
  submitLabel?: string;
  submitBusyLabel?: string;
  // Inline error displayed above footer.
  submitError?: string | null;

  onCancel: () => void;
  onBack: () => void;
  onNext: () => void;
  onSubmit: () => void;

  // Active step content panel.
  children: ReactNode;
};

export function WizardChrome({
  stepLabels,
  currentStep,
  canAdvance,
  isPending = false,
  submitLabel = "Save",
  submitBusyLabel = "Saving…",
  submitError,
  onCancel,
  onBack,
  onNext,
  onSubmit,
  children,
}: WizardChromeProps) {
  const totalSteps = stepLabels.length;
  const isLastStep = currentStep >= totalSteps;
  const stepIndex = currentStep - 1;
  const currentLabel = stepLabels[stepIndex] ?? "";

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <ol className="flex items-center gap-2" aria-label="Wizard progress">
          {stepLabels.map((_, i) => {
            const n = i + 1;
            const isActive = currentStep === n;
            const isPast = currentStep > n;
            return (
              <li key={n} className="flex items-center gap-2">
                <span
                  aria-current={isActive ? "step" : undefined}
                  className={cn(
                    "flex h-6 w-6 items-center justify-center rounded-full border text-xs font-medium",
                    isActive &&
                      "border-primary bg-primary text-primary-foreground",
                    isPast && "border-primary bg-primary/10 text-primary",
                    !isActive &&
                      !isPast &&
                      "border-border text-muted-foreground",
                  )}
                >
                  {isPast ? <Check className="h-3 w-3" /> : n}
                </span>
                {n < totalSteps ? (
                  <span
                    className="h-px w-6 bg-border"
                    aria-hidden="true"
                  />
                ) : null}
              </li>
            );
          })}
        </ol>
        <p className="text-caption text-muted-foreground">
          Step {currentStep} of {totalSteps}:{" "}
          <span className="text-foreground">{currentLabel}</span>
        </p>
      </div>

      <div className="flex flex-col rounded-md border border-border bg-card/20 p-6">
        {children}
      </div>

      {submitError ? <ErrorInline message={submitError} /> : null}

      <div className="flex items-center justify-between gap-3">
        <Button variant="ghost" disabled={isPending} onClick={onCancel}>
          Cancel
        </Button>
        <div className="flex items-center gap-2">
          {currentStep > 1 ? (
            <Button variant="outline" onClick={onBack} disabled={isPending}>
              Back
            </Button>
          ) : null}
          {!isLastStep ? (
            <Button onClick={onNext} disabled={!canAdvance}>
              Next
            </Button>
          ) : (
            <Button onClick={onSubmit} disabled={!canAdvance || isPending}>
              {isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {submitBusyLabel}
                </>
              ) : (
                submitLabel
              )}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
