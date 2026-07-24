"use client";

import { Check, Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";
import { WIZARD_STEPS, type WizardStepKey } from "./wizard-steps";

export type RailState = "complete" | "current" | "pending" | "disabled";

export type StepRailProps = {
  activeKey: WizardStepKey;
  stateFor: (key: WizardStepKey) => RailState;
  onSelect: (key: WizardStepKey) => void;
  // Draft-saved indicator.
  saving: boolean;
  savedLabel: string | null;
};

export function StepRail({
  activeKey,
  stateFor,
  onSelect,
  saving,
  savedLabel,
}: StepRailProps) {
  return (
    <nav
      aria-label="Onboarding steps"
      className="flex w-64 shrink-0 flex-col gap-1 border-r border-border p-4"
    >
      <ol className="flex flex-col gap-1">
        {WIZARD_STEPS.map((step, index) => {
          const state = stateFor(step.key);
          const clickable = state !== "disabled" && step.key !== activeKey;
          return (
            <li key={step.key}>
              <button
                type="button"
                disabled={!clickable}
                aria-current={state === "current" ? "step" : undefined}
                onClick={() => clickable && onSelect(step.key)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors",
                  "focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                  state === "current" && "bg-muted font-medium text-foreground",
                  state === "complete" && "text-foreground hover:bg-muted",
                  state === "pending" && "text-muted-foreground hover:bg-muted",
                  state === "disabled" &&
                    "cursor-not-allowed text-muted-foreground/50",
                )}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs",
                    state === "complete" &&
                      "border-emerald-500 bg-emerald-500 text-white dark:border-emerald-400 dark:bg-emerald-400 dark:text-emerald-950",
                    state === "current" && "border-primary text-primary",
                    state === "pending" && "border-border text-muted-foreground",
                    state === "disabled" &&
                      "border-border/50 text-muted-foreground/50",
                  )}
                >
                  {state === "complete" ? (
                    <Check className="h-3.5 w-3.5" />
                  ) : (
                    index + 1
                  )}
                </span>
                <span className="min-w-0 flex-1 truncate">{step.label}</span>
                {state === "disabled" ? (
                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground/60">
                    Soon
                  </span>
                ) : null}
              </button>
            </li>
          );
        })}
      </ol>

      <div className="mt-2 border-t border-border px-3 pt-3 text-xs text-muted-foreground">
        {saving ? (
          <span className="inline-flex items-center gap-1.5">
            <Loader2 className="h-3 w-3 animate-spin" />
            Saving...
          </span>
        ) : savedLabel ? (
          <span className="inline-flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400">
            <Check className="h-3 w-3" />
            {savedLabel}
          </span>
        ) : (
          <span>Draft not yet saved</span>
        )}
      </div>
    </nav>
  );
}
