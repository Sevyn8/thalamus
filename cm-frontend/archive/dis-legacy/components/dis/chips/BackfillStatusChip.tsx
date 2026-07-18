import { Chip, type Tone } from "@/components/shared/Chips";
import type { BackfillStatus } from "@/types/dis";

const STATUS_TONE: Record<BackfillStatus, Tone> = {
  QUEUED: "grey",
  RUNNING: "blue",
  SUCCEEDED: "green",
  PARTIALLY_SUCCEEDED: "amber",
  FAILED: "red",
  CANCELED: "grey",
};

const STATUS_LABEL: Record<BackfillStatus, string> = {
  QUEUED: "Queued",
  RUNNING: "Running",
  SUCCEEDED: "Succeeded",
  PARTIALLY_SUCCEEDED: "Partial",
  FAILED: "Failed",
  CANCELED: "Canceled",
};

export function BackfillStatusChip({ status }: { status: BackfillStatus }) {
  return <Chip tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</Chip>;
}
