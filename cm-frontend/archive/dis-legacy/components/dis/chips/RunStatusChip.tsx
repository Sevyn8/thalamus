import { Chip, type Tone } from "@/components/shared/Chips";
import type { RunStatus } from "@/types/dis";

const STATUS_TONE: Record<RunStatus, Tone> = {
  QUEUED: "grey",
  RUNNING: "blue",
  SUCCEEDED: "green",
  FAILED: "red",
  CANCELED: "amber",
};

const STATUS_LABEL: Record<RunStatus, string> = {
  QUEUED: "Queued",
  RUNNING: "Running",
  SUCCEEDED: "Succeeded",
  FAILED: "Failed",
  CANCELED: "Canceled",
};

export function RunStatusChip({ status }: { status: RunStatus }) {
  return <Chip tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</Chip>;
}
