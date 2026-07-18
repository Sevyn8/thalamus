import { Chip, type Tone } from "@/components/shared/Chips";
import type { FreshnessState } from "@/types/dis";

const STATE_TONE: Record<FreshnessState, Tone> = {
  FRESH: "green",
  DELAYED: "amber",
  STALE: "red",
  // CRITICAL maps to the same red tone — there's no "deeper red" tone
  // in the shared palette. Visual distinction lands via sort order
  // (CRITICAL surfaces first) and the explicit label.
  CRITICAL: "red",
  UNKNOWN: "grey",
};

const STATE_LABEL: Record<FreshnessState, string> = {
  FRESH: "Fresh",
  DELAYED: "Delayed",
  STALE: "Stale",
  CRITICAL: "Critical",
  UNKNOWN: "Unknown",
};

export function FreshnessStateChip({ state }: { state: FreshnessState }) {
  return <Chip tone={STATE_TONE[state]}>{STATE_LABEL[state]}</Chip>;
}
