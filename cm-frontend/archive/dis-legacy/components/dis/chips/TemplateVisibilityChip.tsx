import { Chip, type Tone } from "@/components/shared/Chips";
import type { TemplateVisibility } from "@/types/dis";

const VISIBILITY_TONE: Record<TemplateVisibility, Tone> = {
  TENANT_SHARED: "green",
  PRIVATE: "grey",
};

const VISIBILITY_LABEL: Record<TemplateVisibility, string> = {
  TENANT_SHARED: "Shared",
  PRIVATE: "Private",
};

export function TemplateVisibilityChip({
  visibility,
}: {
  visibility: TemplateVisibility;
}) {
  return <Chip tone={VISIBILITY_TONE[visibility]}>{VISIBILITY_LABEL[visibility]}</Chip>;
}
