"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { ApiError } from "@/lib/api/client";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { useSource } from "@/lib/dis/hooks/use-sources";
import { useCreateStream } from "@/lib/dis/hooks/use-streams";
import { WizardChrome } from "@/lib/dis/components/Wizard";
import type { Source, StreamDomain } from "@/types/dis";

import { StepDomain } from "./wizard-steps/StepDomain";
import { StepSourcePicker } from "./wizard-steps/StepSourcePicker";
import {
  StepStreamReview,
} from "./wizard-steps/StepStreamReview";
import {
  StepStreamSchedule,
  isCronValid,
} from "./wizard-steps/StepStreamSchedule";

// Phase 5e.4d: 4-step wizard for new stream. When `prebindSourceId`
// is provided (via /dis/streams/new?source={id}), Step 1 is skipped
// — the wizard runs as a 3-step (Domain / Schedule / Name) flow over
// the pre-bound source. This is the elegant alternative to a chained
// AddSource → AddStream wizard: same wizard, different entry points,
// different step counts.

type Props = {
  prebindSourceId: string | null;
};

type FullStep = 1 | 2 | 3 | 4;

const FULL_STEP_LABELS = ["Source", "Domain", "Schedule", "Name"] as const;
const PREBIND_STEP_LABELS = ["Domain", "Schedule", "Name"] as const;

export function AddStreamWizard({ prebindSourceId }: Props) {
  const router = useRouter();
  const snapshot = useAuthSnapshot();
  const tenantId = snapshot?.user.tenantId ?? null;
  const mutation = useCreateStream();

  // Pre-bound mode: skip step 1; query the source eagerly so the
  // wizard has its denorm context for the review card.
  const prebindQuery = useSource(prebindSourceId ?? "");

  const [step, setStep] = useState<FullStep>(prebindSourceId ? 2 : 1);
  const [source, setSource] = useState<Source | null>(null);
  const [domain, setDomain] = useState<StreamDomain | null>(null);
  const [schedule, setSchedule] = useState("");
  const [name, setName] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Seed pre-bound source once query lands.
  const prebindSource = prebindQuery.data;
  if (prebindSource && source?.id !== prebindSource.id && prebindSourceId) {
    setSource(prebindSource);
  }

  if (!tenantId) {
    return (
      <div className="rounded-md border border-border bg-card/30 p-6">
        <p className="text-sm">
          Stream creation requires a tenant context. Switch to a tenant persona.
        </p>
      </div>
    );
  }

  if (prebindSourceId && prebindQuery.isLoading) {
    return <Skeleton variant="row" count={4} />;
  }
  if (prebindSourceId && (prebindQuery.error || !prebindSource)) {
    return (
      <ErrorInline
        message="Could not load the source to bind this stream to."
        onRetry={() => prebindQuery.refetch()}
      />
    );
  }

  const isPrebound = !!prebindSourceId;
  const stepLabels = isPrebound
    ? [...PREBIND_STEP_LABELS]
    : [...FULL_STEP_LABELS];
  // Map wizard's internal 1..4 to chrome's displayed 1..3 when pre-bound.
  const displayStep = isPrebound ? step - 1 : step;

  const canAdvance: Record<FullStep, boolean> = {
    1: source !== null,
    2: domain !== null,
    3: isCronValid(schedule),
    4: name.trim().length > 0,
  };

  async function onSave() {
    if (!source || !domain || !canAdvance[4]) return;
    setSubmitError(null);
    try {
      const created = await mutation.mutateAsync({
        source_id: source.id,
        name: name.trim(),
        domain,
        schedule: schedule.trim(),
      });
      router.push(`/dis/streams/${created.id}`);
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Save failed. Try again.");
    }
  }

  const stepContent =
    step === 1 ? (
      <StepSourcePicker
        selectedSourceId={source?.id ?? null}
        onSelect={setSource}
      />
    ) : step === 2 ? (
      <StepDomain selected={domain} onChange={setDomain} />
    ) : step === 3 ? (
      <StepStreamSchedule
        schedule={schedule}
        onScheduleChange={setSchedule}
      />
    ) : (
      <StepStreamReview
        name={name}
        source={source!}
        domain={domain!}
        schedule={schedule}
        onNameChange={setName}
      />
    );

  function onBack() {
    setStep((s) => {
      const next = (s - 1) as FullStep;
      // Pre-bound mode: can't back into step 1 (the source picker
      // doesn't apply); clamp at step 2.
      return isPrebound && next < 2 ? 2 : next;
    });
  }

  function onNext() {
    setStep((s) => (s + 1) as FullStep);
  }

  return (
    <WizardChrome
      stepLabels={stepLabels}
      currentStep={displayStep}
      canAdvance={canAdvance[step]}
      isPending={mutation.isPending}
      submitLabel="Save stream"
      submitError={submitError}
      onCancel={() => router.push("/dis/sources")}
      onBack={onBack}
      onNext={onNext}
      onSubmit={onSave}
    >
      {stepContent}
    </WizardChrome>
  );
}
