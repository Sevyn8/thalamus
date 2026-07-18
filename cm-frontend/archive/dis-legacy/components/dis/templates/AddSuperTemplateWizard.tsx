"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError } from "@/lib/api/client";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { useCanonicalSchema } from "@/lib/dis/hooks/use-canonical-schema";
import { useCreateTemplate } from "@/lib/dis/hooks/use-templates";
import { WizardChrome } from "@/lib/dis/components/Wizard";
import type { TemplateDomain, TemplateVisibility } from "@/types/dis";

import { StepPickDomains } from "./wizard-steps/StepPickDomains";
import { StepTemplateMeta } from "./wizard-steps/StepTemplateMeta";
import { StepTemplateReview } from "./wizard-steps/StepTemplateReview";

// Phase 5e.6: 3-step Super Template creation wizard.
//   1. Pick domains (multi-select, ≥2 required)
//   2. Name + description + visibility
//   3. Review (column preview + submit)
//
// Cancel = silent discard. Back-navigation preserves all step values.
// No pre-bound mode (no parent surface that would pre-fill state).

type Step = 1 | 2 | 3;

const STEP_LABELS = ["Domains", "Details", "Review"] as const;

export function AddSuperTemplateWizard() {
  const router = useRouter();
  const snapshot = useAuthSnapshot();
  const tenantId = snapshot?.user.tenantId ?? null;
  const mutation = useCreateTemplate();
  const schemaQuery = useCanonicalSchema();

  const [step, setStep] = useState<Step>(1);
  const [domains, setDomains] = useState<TemplateDomain[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<TemplateVisibility>("TENANT_SHARED");
  const [submitError, setSubmitError] = useState<string | null>(null);

  function toggleDomain(d: TemplateDomain) {
    setDomains((prev) =>
      prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d],
    );
  }

  const domainPreviews = useMemo(() => {
    const all = schemaQuery.data?.domains ?? [];
    return domains.map((d) => {
      const match = all.find((sd) => sd.id === d);
      return {
        domain: d,
        fieldIds: match?.fields.map((f) => f.id) ?? [],
      };
    });
  }, [domains, schemaQuery.data]);

  const canAdvance: Record<Step, boolean> = {
    1: domains.length >= 2,
    2: name.trim().length > 0,
    3: true,
  };

  async function onSave() {
    if (!canAdvance[3] || !canAdvance[2] || !canAdvance[1]) return;
    setSubmitError(null);
    try {
      const created = await mutation.mutateAsync({
        kind: "SUPER",
        name: name.trim(),
        description: description.trim(),
        visibility,
        domains,
      });
      router.push(`/dis/templates/${created.id}`);
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Save failed. Try again.");
    }
  }

  if (!tenantId) {
    return (
      <div className="rounded-md border border-border bg-card/30 p-6">
        <p className="text-sm">
          Super Template creation requires a tenant context. Switch to a
          tenant persona.
        </p>
      </div>
    );
  }

  const stepContent =
    step === 1 ? (
      <StepPickDomains selected={domains} onToggle={toggleDomain} />
    ) : step === 2 ? (
      <StepTemplateMeta
        name={name}
        description={description}
        visibility={visibility}
        onNameChange={setName}
        onDescriptionChange={setDescription}
        onVisibilityChange={setVisibility}
      />
    ) : (
      <StepTemplateReview
        name={name}
        description={description}
        visibility={visibility}
        domainPreviews={domainPreviews}
      />
    );

  return (
    <WizardChrome
      stepLabels={[...STEP_LABELS]}
      currentStep={step}
      canAdvance={canAdvance[step]}
      isPending={mutation.isPending}
      submitLabel="Save Super Template"
      submitError={submitError}
      onCancel={() => router.push("/dis/templates")}
      onBack={() => setStep((s) => (s - 1) as Step)}
      onNext={() => setStep((s) => (s + 1) as Step)}
      onSubmit={onSave}
    >
      {stepContent}
    </WizardChrome>
  );
}
