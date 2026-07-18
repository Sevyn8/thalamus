import { Chip, type Tone } from "@/components/shared/Chips";
import type { DisLifecycleState } from "@/types/dis";

// Phase 5e.10b: tenant DIS lifecycle chip for the operational
// dashboard. Recreated after 5e.10a retired the provisioning
// surface (and its parallel DisProvisioningStateChip). Same
// 5-state palette + Chip primitive — semantic context shifted
// from "provisioning row" to "tenant operational header."
//
// State semantics:
//   NEW         blue   — DIS enabled, no streams yet
//   ONBOARDING  amber  — streams exist or DIS enabled, no recent ingest
//   ACTIVE      green  — healthy, ingesting
//   SUSPENDED   grey   — admin-paused
//   TERMINATED  red    — tenant terminated

const STATE_TONE: Record<DisLifecycleState, Tone> = {
  NEW: "blue",
  ONBOARDING: "amber",
  ACTIVE: "green",
  SUSPENDED: "grey",
  TERMINATED: "red",
};

const STATE_LABEL: Record<DisLifecycleState, string> = {
  NEW: "New",
  ONBOARDING: "Onboarding",
  ACTIVE: "Active",
  SUSPENDED: "Suspended",
  TERMINATED: "Terminated",
};

export function DisLifecycleStateChip({
  state,
}: {
  state: DisLifecycleState;
}) {
  return <Chip tone={STATE_TONE[state]}>{STATE_LABEL[state]}</Chip>;
}
