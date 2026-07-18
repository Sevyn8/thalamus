import { Chip, type Tone } from "@/components/shared/Chips";
import type { StreamDomain } from "@/types/dis";

// Phase 5e.4b: stream-domain chip (sales / inventory / customers /
// suppliers / stores / products). Reuses the established Chip
// primitive + the tone palette from Chips.tsx. Tone choices follow
// the OrgNodeTypeBadge precedent (6+ types each with a distinct hue).

const DOMAIN_TONE: Record<StreamDomain, Tone> = {
  sales: "blue",
  inventory: "teal",
  customers: "violet",
  suppliers: "amber",
  stores: "green",
  products: "purple",
};

const DOMAIN_LABEL: Record<StreamDomain, string> = {
  sales: "Sales",
  inventory: "Inventory",
  customers: "Customers",
  suppliers: "Suppliers",
  stores: "Stores",
  products: "Products",
};

export function StreamDomainChip({ domain }: { domain: StreamDomain }) {
  return <Chip tone={DOMAIN_TONE[domain]}>{DOMAIN_LABEL[domain]}</Chip>;
}
