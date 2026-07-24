// The onboarding wizard's 7 steps. Keys match the backend's fixed
// WIZARD_SECTION_KEYS set (validated by PATCH /tenants/{id}/onboarding for
// current_step and every section_status key). Step 6 (access) is
// implemented in Slice 5; step 7 (review) renders as a disabled placeholder
// until a later slice. The order here is the rail order and the
// Save-&-continue advance order.

export type WizardStepKey =
  | "company"
  | "legal"
  | "billing"
  | "contacts"
  | "documents"
  | "access"
  | "review";

export type WizardStep = {
  key: WizardStepKey;
  label: string;
  // Implemented this slice (1-5) vs disabled placeholder (6-7).
  enabled: boolean;
};

export const WIZARD_STEPS: readonly WizardStep[] = [
  { key: "company", label: "Company profile", enabled: true },
  { key: "legal", label: "Legal & statutory", enabled: true },
  { key: "billing", label: "Billing & finance", enabled: true },
  { key: "contacts", label: "Contacts", enabled: true },
  { key: "documents", label: "Documents", enabled: true },
  { key: "access", label: "Access & users", enabled: true },
  { key: "review", label: "Review & confirm", enabled: false },
];

export const ENABLED_STEP_KEYS: readonly WizardStepKey[] = WIZARD_STEPS.filter(
  (s) => s.enabled,
).map((s) => s.key);

export function isWizardStepKey(v: string | null): v is WizardStepKey {
  return v !== null && WIZARD_STEPS.some((s) => s.key === v);
}

// The next enabled step after `key`, or null if none (documents is the
// last enabled step this slice).
export function nextEnabledStep(key: WizardStepKey): WizardStepKey | null {
  const idx = WIZARD_STEPS.findIndex((s) => s.key === key);
  for (let i = idx + 1; i < WIZARD_STEPS.length; i += 1) {
    const step = WIZARD_STEPS[i];
    if (step && step.enabled) return step.key;
  }
  return null;
}

export function prevEnabledStep(key: WizardStepKey): WizardStepKey | null {
  const idx = WIZARD_STEPS.findIndex((s) => s.key === key);
  for (let i = idx - 1; i >= 0; i -= 1) {
    const step = WIZARD_STEPS[i];
    if (step && step.enabled) return step.key;
  }
  return null;
}
