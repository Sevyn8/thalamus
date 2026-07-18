"use client";

import { cn } from "@/lib/utils";
import type { TemplateDomain } from "@/types/dis";

// Phase 5e.6 step 1: pick the 2+ canonical domains the Super
// Template should combine. Multi-select grid mirrors AddStreamWizard's
// StepDomain visual shape but allows toggling multiple cards.

type Card = {
  domain: TemplateDomain;
  label: string;
  description: string;
};

const CARDS: Card[] = [
  { domain: "sales", label: "Sales", description: "Transactions, orders, line-item revenue." },
  { domain: "inventory", label: "Inventory", description: "Stock levels, restocks, shrinkage." },
  { domain: "customers", label: "Customers", description: "Loyalty members, profiles, PII-flagged identifiers." },
  { domain: "suppliers", label: "Suppliers", description: "Vendor relationships, purchase orders." },
  { domain: "stores", label: "Stores", description: "Locations, regions, operating metadata." },
  { domain: "products", label: "Products", description: "SKU catalog, categories, pricing tiers." },
];

type Props = {
  selected: TemplateDomain[];
  onToggle: (domain: TemplateDomain) => void;
};

export function StepPickDomains({ selected, onToggle }: Props) {
  return (
    <div className="flex flex-col gap-3">
      <p className="text-caption text-muted-foreground">
        Pick 2 or more canonical domains to combine into a single CSV.
        Each selected domain&apos;s fields will be auto-populated as
        columns in the template, in the order you pick them. Add
        prefixes resolve overlapping field names across domains
        (e.g. <code className="font-mono text-xs">sales.store_code</code>{" "}
        vs <code className="font-mono text-xs">stores.store_code</code>).
      </p>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {CARDS.map(({ domain, label, description }) => {
          const isSelected = selected.includes(domain);
          return (
            <button
              key={domain}
              type="button"
              onClick={() => onToggle(domain)}
              aria-pressed={isSelected}
              className={cn(
                "flex flex-col items-start gap-2 rounded-md border p-4 text-left transition-colors duration-150 ease-out",
                isSelected
                  ? "border-primary bg-primary/5"
                  : "border-border bg-card/30 hover:border-border-strong hover:bg-surface-raised",
              )}
            >
              <div className="flex w-full items-center justify-between">
                <span className="text-body-strong">{label}</span>
                {isSelected ? (
                  <span className="text-xs font-medium text-primary">
                    #{selected.indexOf(domain) + 1}
                  </span>
                ) : null}
              </div>
              <span className="text-caption text-muted-foreground">{description}</span>
            </button>
          );
        })}
      </div>
      {selected.length > 0 ? (
        <p className="text-caption text-muted-foreground">
          {selected.length === 1
            ? "Pick at least 1 more domain to enable Super Template creation."
            : `${selected.length} domains selected. Order: ${selected.join(" → ")}.`}
        </p>
      ) : null}
    </div>
  );
}
