import { Chip, type Tone } from "@/components/shared/Chips";
import type { UploadStatus } from "@/types/dis";

// First DIS-domain chip composed from the Phase 5b.3 exported Chip
// primitive. Sets the pattern for follow-on DIS chips (RunStatus,
// StreamHealth, AlertSeverity, FreshnessState, ValidationResult,
// DriftSeverity) — each lives next to its consumer feature with its
// own tone table and label table, no coupling into Ithina's chip
// type union.

const STATUS_TONE: Record<UploadStatus, Tone> = {
  PENDING_REVIEW: "amber",
  CONFIRMED: "blue",
  MID_INGEST: "blue",
  COMPLETED: "green",
  FAILED_VALIDATION: "red",
};

const STATUS_LABEL: Record<UploadStatus, string> = {
  PENDING_REVIEW: "Pending review",
  CONFIRMED: "Confirmed",
  MID_INGEST: "Ingesting",
  COMPLETED: "Completed",
  FAILED_VALIDATION: "Failed validation",
};

export function UploadStatusChip({ status }: { status: UploadStatus }) {
  return <Chip tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</Chip>;
}
