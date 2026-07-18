import { Chip, type Tone } from "@/components/shared/Chips";
import type { CanonicalSchemaFieldType } from "@/types/dis";

const TYPE_TONE: Record<CanonicalSchemaFieldType, Tone> = {
  string: "blue",
  number: "violet",
  datetime: "teal",
  boolean: "amber",
  enum: "grey",
};

const TYPE_LABEL: Record<CanonicalSchemaFieldType, string> = {
  string: "string",
  number: "number",
  datetime: "datetime",
  boolean: "boolean",
  enum: "enum",
};

export function CanonicalFieldTypeChip({
  type,
}: {
  type: CanonicalSchemaFieldType;
}) {
  return <Chip tone={TYPE_TONE[type]}>{TYPE_LABEL[type]}</Chip>;
}
