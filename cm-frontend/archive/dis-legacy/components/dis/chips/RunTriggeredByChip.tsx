import { Chip, type Tone } from "@/components/shared/Chips";
import type { RunTriggeredBy } from "@/types/dis";

// Quieter tone palette than RunStatus — triggered_by is metadata, not
// an attention-grabbing operational signal. Greys + a single subtle
// blue for SCHEDULE (the default ~80% of runs).
const TRIGGER_TONE: Record<RunTriggeredBy, Tone> = {
  SCHEDULE: "grey",
  MANUAL: "blue",
  BACKFILL: "violet",
  API: "teal",
};

const TRIGGER_LABEL: Record<RunTriggeredBy, string> = {
  SCHEDULE: "Schedule",
  MANUAL: "Manual",
  BACKFILL: "Backfill",
  API: "API",
};

export function RunTriggeredByChip({
  triggeredBy,
}: {
  triggeredBy: RunTriggeredBy;
}) {
  return (
    <Chip tone={TRIGGER_TONE[triggeredBy]}>{TRIGGER_LABEL[triggeredBy]}</Chip>
  );
}
