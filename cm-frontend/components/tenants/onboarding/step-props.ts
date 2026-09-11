// Shared prop contract for the content steps (legal / billing / contacts /
// documents) that operate on an existing tenant. The shell passes the
// tenant id, an onSaved callback (which persists current_step +
// section_status and advances), a Back handler (null on the first enabled
// step), and a setDirty reporter so the shell can guard navigation away
// from an unsaved step. The company step has its own (create-or-edit)
// contract in CompanyProfileStep.
//
// `mode` distinguishes the two surfaces the wizard serves. In "onboarding"
// mode onSaved advances to the next step (the
// existing linear flow). In "edit" mode (the retired EditTenantModal's
// replacement) each section is a standalone edit surface: onSaved is a
// server-wait save that only toasts and stays put, the footer reads
// "Save changes", and immediate-apply steps (documents / access) drop
// their footer entirely because their actions persist on the spot.
export type WizardMode = "onboarding" | "edit";

export type StepProps = {
  tenantId: string;
  onSaved: () => void;
  onBack: (() => void) | null;
  setDirty: (dirty: boolean) => void;
  mode: WizardMode;
};
