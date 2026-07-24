// Shared prop contract for the content steps (legal / billing / contacts /
// documents) that operate on an existing tenant. The shell passes the
// tenant id, an onSaved callback (which persists current_step +
// section_status and advances), a Back handler (null on the first enabled
// step), and a setDirty reporter so the shell can guard navigation away
// from an unsaved step. The company step has its own (create-or-edit)
// contract in CompanyProfileStep.
export type StepProps = {
  tenantId: string;
  onSaved: () => void;
  onBack: (() => void) | null;
  setDirty: (dirty: boolean) => void;
};
