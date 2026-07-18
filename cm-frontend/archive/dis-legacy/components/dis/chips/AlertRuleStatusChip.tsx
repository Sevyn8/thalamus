import { Chip, type Tone } from "@/components/shared/Chips";

const STATUS_TONE: Record<"enabled" | "disabled", Tone> = {
  enabled: "green",
  disabled: "grey",
};

const STATUS_LABEL: Record<"enabled" | "disabled", string> = {
  enabled: "Enabled",
  disabled: "Disabled",
};

export function AlertRuleStatusChip({ enabled }: { enabled: boolean }) {
  const key = enabled ? "enabled" : "disabled";
  return <Chip tone={STATUS_TONE[key]}>{STATUS_LABEL[key]}</Chip>;
}
