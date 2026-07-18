import { Chip, type Tone } from "@/components/shared/Chips";
import type { AlertEventState } from "@/types/dis";

const STATE_TONE: Record<AlertEventState, Tone> = {
  UNRESOLVED: "red",
  ACKNOWLEDGED: "amber",
  RESOLVED: "green",
};

const STATE_LABEL: Record<AlertEventState, string> = {
  UNRESOLVED: "Unresolved",
  ACKNOWLEDGED: "Acknowledged",
  RESOLVED: "Resolved",
};

export function AlertEventStateChip({ state }: { state: AlertEventState }) {
  return <Chip tone={STATE_TONE[state]}>{STATE_LABEL[state]}</Chip>;
}
