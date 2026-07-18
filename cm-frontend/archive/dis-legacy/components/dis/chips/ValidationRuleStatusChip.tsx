import { Chip, type Tone } from "@/components/shared/Chips";
import type { ValidationRuleStatus } from "@/types/dis";

const STATUS_TONE: Record<ValidationRuleStatus, Tone> = {
  ACTIVE: "green",
  DISABLED: "grey",
};

const STATUS_LABEL: Record<ValidationRuleStatus, string> = {
  ACTIVE: "Active",
  DISABLED: "Disabled",
};

export function ValidationRuleStatusChip({
  status,
}: {
  status: ValidationRuleStatus;
}) {
  return <Chip tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</Chip>;
}
