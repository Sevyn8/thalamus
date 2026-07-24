"use client";

import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";

export type WizardFooterProps = {
  formId: string;
  saving: boolean;
  onBack: (() => void) | null;
  continueLabel?: string;
  continueDisabled?: boolean;
};

// Shared step footer: Back (if a previous enabled step exists) + the
// step form's submit button (wired via form= to the step's <form id>).
export function WizardFooter({
  formId,
  saving,
  onBack,
  continueLabel = "Save & continue",
  continueDisabled,
}: WizardFooterProps) {
  return (
    <div className="flex items-center justify-between border-t border-border px-6 py-4">
      <div>
        {onBack ? (
          <Button type="button" variant="outline" onClick={onBack} disabled={saving}>
            Back
          </Button>
        ) : null}
      </div>
      <Button
        type="submit"
        form={formId}
        disabled={saving || continueDisabled}
      >
        {saving ? (
          <>
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            Saving...
          </>
        ) : (
          continueLabel
        )}
      </Button>
    </div>
  );
}
