"use client";

import { cn } from "@/lib/utils";
import type { StreamDomain } from "@/types/dis";

// Phase 5e.4d step 2: domain picker. 6 options on a 2/3-column grid.
// Mirrors StepType visual shape (cards with label + description) but
// without icons in v1 — StreamDomainChip carries the color signal
// elsewhere; here we just need a clear pickable card per domain.

type Card = {
  domain: StreamDomain;
  label: string;
  description: string;
};

const CARDS: Card[] = [
  { domain: "sales", label: "Sales", description: "Transactions, orders, line items." },
  { domain: "inventory", label: "Inventory", description: "Stock counts, warehouse snapshots." },
  { domain: "customers", label: "Customers", description: "Loyalty, profiles, identifiers." },
  { domain: "suppliers", label: "Suppliers", description: "Vendor records, purchase orders." },
  { domain: "stores", label: "Stores", description: "Store metadata, locations, hierarchy." },
  { domain: "products", label: "Products", description: "Catalog, SKUs, promotions." },
];

type Props = {
  selected: StreamDomain | null;
  onChange: (domain: StreamDomain) => void;
};

export function StepDomain({ selected, onChange }: Props) {
  return (
    <div className="flex flex-col gap-3">
      <p className="text-caption text-muted-foreground">
        What kind of data does this feed deliver? Each domain has its
        own canonical schema; the mapping engine routes accordingly.
      </p>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {CARDS.map(({ domain, label, description }) => {
          const isSelected = selected === domain;
          return (
            <button
              key={domain}
              type="button"
              onClick={() => onChange(domain)}
              aria-pressed={isSelected}
              className={cn(
                "flex flex-col items-start gap-2 rounded-md border p-4 text-left transition-colors duration-150 ease-out",
                isSelected
                  ? "border-primary bg-primary/5"
                  : "border-border bg-card/30 hover:border-border-strong hover:bg-surface-raised",
              )}
            >
              <span className="text-body-strong">{label}</span>
              <span className="text-caption text-muted-foreground">{description}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
