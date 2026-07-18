import { Chip, type Tone } from "@/components/shared/Chips";
import type { StreamStatus, SystemStatus } from "@/types/dis";

// Phase 5e.4c: chip accepts either status type (SystemStatus on
// Source, StreamStatus on Stream). Both unions resolve to the same
// 4 string values today; keeping them as named param types keeps
// downstream call sites readable. Filename retained as
// SourceStatusChip — generic-status-chip rename deferred (low value).

type AnyStatus = SystemStatus | StreamStatus;

const STATUS_TONE: Record<AnyStatus, Tone> = {
  ACTIVE: "green",
  PAUSED: "amber",
  ERROR: "red",
  ONBOARDING: "blue",
};

const STATUS_LABEL: Record<AnyStatus, string> = {
  ACTIVE: "Active",
  PAUSED: "Paused",
  ERROR: "Error",
  ONBOARDING: "Onboarding",
};

export function SourceStatusChip({ status }: { status: AnyStatus }) {
  return <Chip tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</Chip>;
}
