import { Chip, type Tone } from "@/components/shared/Chips";
import type { ValidationSeverity } from "@/types/dis";

const SEVERITY_TONE: Record<ValidationSeverity, Tone> = {
  ERROR: "red",
  WARNING: "amber",
  INFO: "blue",
};

const SEVERITY_LABEL: Record<ValidationSeverity, string> = {
  ERROR: "Error",
  WARNING: "Warning",
  INFO: "Info",
};

export function ValidationSeverityChip({
  severity,
}: {
  severity: ValidationSeverity;
}) {
  return (
    <Chip tone={SEVERITY_TONE[severity]}>{SEVERITY_LABEL[severity]}</Chip>
  );
}
