import { Chip, type Tone } from "@/components/shared/Chips";
import type { AlertSeverity } from "@/types/dis";

const SEVERITY_TONE: Record<AlertSeverity, Tone> = {
  CRITICAL: "red",
  WARNING: "amber",
  INFO: "blue",
};

const SEVERITY_LABEL: Record<AlertSeverity, string> = {
  CRITICAL: "Critical",
  WARNING: "Warning",
  INFO: "Info",
};

export function AlertSeverityChip({ severity }: { severity: AlertSeverity }) {
  return <Chip tone={SEVERITY_TONE[severity]}>{SEVERITY_LABEL[severity]}</Chip>;
}
