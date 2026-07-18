import { Chip, type Tone } from "@/components/shared/Chips";
import type { DriftSeverity } from "@/types/dis";

const SEVERITY_TONE: Record<DriftSeverity, Tone> = {
  BREAKING: "red",
  WARNING: "amber",
  INFO: "blue",
};

const SEVERITY_LABEL: Record<DriftSeverity, string> = {
  BREAKING: "Breaking",
  WARNING: "Warning",
  INFO: "Info",
};

export function DriftSeverityChip({ severity }: { severity: DriftSeverity }) {
  return <Chip tone={SEVERITY_TONE[severity]}>{SEVERITY_LABEL[severity]}</Chip>;
}
