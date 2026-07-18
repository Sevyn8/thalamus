"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError } from "@/lib/api/client";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { useCreateSource } from "@/lib/dis/hooks/use-sources";
import { WizardChrome } from "@/lib/dis/components/Wizard";
import type { OrgNodeTreeItem } from "@/types/api";
import type { ConnectionConfig, SystemKind } from "@/types/dis";

import { StepConfig } from "./wizard-steps/StepConfig";
import { StepOrgNode } from "./wizard-steps/StepOrgNode";
import { StepSourceName } from "./wizard-steps/StepSourceName";
import { StepTest } from "./wizard-steps/StepTest";
import { StepType } from "./wizard-steps/StepType";

// Phase 5e.4d: renamed from CreateSourceWizard. Step 5 narrowed from
// "Schedule" (cron + name) to "Name" — schedule moved to Stream level
// per Source/Stream split (see [[source-stream-id-mapping]]).
// AddStreamWizard ships separately with its own 3-or-4 step flow.
// Wizard state lives entirely in this component. Cancel = silent
// discard. Back-navigation preserves all step values. Test result
// is held by StepTest internally; testSucceeded is lifted up here
// to gate Step 5 advance.

type Step = 1 | 2 | 3 | 4 | 5;

const STEP_LABELS = ["Type", "Org node", "Config", "Test", "Name"] as const;

export function AddSourceWizard() {
  const router = useRouter();
  const snapshot = useAuthSnapshot();
  const tenantId = snapshot?.user.tenantId ?? null;
  const mutation = useCreateSource();

  const [step, setStep] = useState<Step>(1);
  const [type, setType] = useState<SystemKind | null>(null);
  const [orgNode, setOrgNode] = useState<OrgNodeTreeItem | null>(null);
  const [connectionConfig, setConnectionConfig] = useState<Partial<ConnectionConfig>>({});
  const [configValid, setConfigValid] = useState(false);
  const [testSucceeded, setTestSucceeded] = useState(false);
  // Phase 5c.2c3: skip-test propagation. Wizard tracks separately so
  // canAdvance[4] enables on (testSucceeded || testSkipped) and the
  // POST payload records untested_at_creation when skipped.
  const [testSkipped, setTestSkipped] = useState(false);
  const [name, setName] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);

  const onConfigChange = useCallback(
    (next: Partial<ConnectionConfig>, valid: boolean) => {
      setConnectionConfig(next);
      setConfigValid(valid);
      // Editing the config invalidates any prior test result.
      setTestSucceeded(false);
    },
    [],
  );

  const onTestResultChange = useCallback((succeeded: boolean) => {
    setTestSucceeded(succeeded);
  }, []);

  const onTestSkipChange = useCallback((skipped: boolean) => {
    setTestSkipped(skipped);
  }, []);

  // When the user changes the source type after Step 1, scrap the
  // config + test draft — different types have different fields, and
  // a stale test result against an old type is misleading.
  function onTypeChange(next: SystemKind) {
    setType(next);
    if (next !== type) {
      setConnectionConfig({});
      setConfigValid(false);
      setTestSucceeded(false);
      setTestSkipped(false);
    }
  }

  const canAdvance: Record<Step, boolean> = {
    1: type !== null,
    2: orgNode !== null,
    3: configValid,
    4: testSucceeded || testSkipped,
    5: name.trim().length > 0,
  };

  async function onSave() {
    if (!type || !orgNode || !canAdvance[5]) return;
    setSubmitError(null);
    try {
      const created = await mutation.mutateAsync({
        name: name.trim(),
        type,
        org_node_id: orgNode.id,
        // Phase 5e.4d: schedule omitted; lives on Stream now. Source
        // is created without a schedule; user adds streams + their
        // schedules in the AddStreamWizard chain (link from source
        // detail Streams tab).
        connection_config: connectionConfig as Record<string, unknown>,
        untested_at_creation: !testSucceeded,
      });
      // Land on the source detail page. The empty Streams tab there
      // surfaces the "Add stream to this source" CTA — 2-click flow
      // for the "I just made a source, now make its first stream"
      // happy path (chained wizard explicitly deferred to 5e.4e).
      router.push(`/dis/sources/${created.id}`);
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Save failed. Try again.");
    }
  }

  if (!tenantId) {
    return (
      <div className="rounded-md border border-border bg-card/30 p-6">
        <p className="text-sm">
          Source creation requires a tenant context. Switch to a tenant persona
          — tenant provisioning is platform-admin scope (handled outside DIS).
        </p>
      </div>
    );
  }

  const stepContent =
    step === 1 ? (
      <StepType selected={type} onChange={onTypeChange} />
    ) : step === 2 ? (
      <StepOrgNode
        tenantId={tenantId}
        selectedNodeId={orgNode?.id ?? null}
        onSelect={setOrgNode}
      />
    ) : step === 3 ? (
      <StepConfig
        type={type!}
        value={connectionConfig}
        onChange={onConfigChange}
      />
    ) : step === 4 ? (
      <StepTest
        type={type!}
        config={connectionConfig}
        onResultChange={onTestResultChange}
        onSkipChange={onTestSkipChange}
        onBackToConfig={() => setStep(3)}
      />
    ) : (
      <StepSourceName
        name={name}
        type={type!}
        orgNodeLabel={
          orgNode
            ? `${orgNode.name}${orgNode.code ? ` (${orgNode.code})` : ""}`
            : null
        }
        onNameChange={setName}
      />
    );

  return (
    <WizardChrome
      stepLabels={[...STEP_LABELS]}
      currentStep={step}
      canAdvance={canAdvance[step]}
      isPending={mutation.isPending}
      submitLabel="Save source"
      submitError={submitError}
      onCancel={() => router.push("/dis/sources")}
      onBack={() => setStep((s) => (s - 1) as Step)}
      onNext={() => setStep((s) => (s + 1) as Step)}
      onSubmit={onSave}
    >
      {stepContent}
    </WizardChrome>
  );
}
