import { Chip, type Tone } from "@/components/shared/Chips";
import type { StreamHealth } from "@/types/dis";

const HEALTH_TONE: Record<StreamHealth, Tone> = {
  HEALTHY: "green",
  DEGRADED: "amber",
  FAILING: "red",
  UNKNOWN: "grey",
};

const HEALTH_LABEL: Record<StreamHealth, string> = {
  HEALTHY: "Healthy",
  DEGRADED: "Degraded",
  FAILING: "Failing",
  UNKNOWN: "Unknown",
};

export function StreamHealthChip({ health }: { health: StreamHealth }) {
  return <Chip tone={HEALTH_TONE[health]}>{HEALTH_LABEL[health]}</Chip>;
}
