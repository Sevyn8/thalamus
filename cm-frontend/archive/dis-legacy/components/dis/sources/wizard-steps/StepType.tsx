"use client";

import {
  Code,
  FileSpreadsheet,
  Globe,
  Plug,
  Server,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { SystemKind } from "@/types/dis";

// Phase 5c.2b1 step 1: type catalog grid. 9 cards laid out 3-column
// on lg, 2-column on md, 1-column on sm. Brand iconography deferred
// per legal review (5c.2a known-deferred); named POS connectors all
// render with lucide Plug + brand text label.

type Card = {
  type: SystemKind;
  label: string;
  description: string;
  icon: LucideIcon;
};

const CARDS: Card[] = [
  { type: "CSV_SCHEDULED", label: "CSV (scheduled)", description: "Recurring CSV pull from URL or FTP.", icon: FileSpreadsheet },
  { type: "SQUARE", label: "Square", description: "Square POS API.", icon: Plug },
  { type: "LIGHTSPEED", label: "Lightspeed", description: "Lightspeed Retail X-Series.", icon: Plug },
  { type: "SHOPIFY_POS", label: "Shopify POS", description: "Shopify POS via Admin API.", icon: Plug },
  { type: "TOAST", label: "Toast", description: "Toast restaurant POS.", icon: Plug },
  { type: "CLOVER", label: "Clover", description: "Clover POS.", icon: Plug },
  { type: "POS_API_GENERIC", label: "POS API (generic)", description: "Catch-all for unlisted POS systems.", icon: Globe },
  { type: "FTP", label: "FTP", description: "Generic FTP file pull.", icon: Server },
  { type: "REST_API_GENERIC", label: "REST API (generic)", description: "Catch-all for ERP / other REST APIs.", icon: Code },
];

type Props = {
  selected: SystemKind | null;
  onChange: (type: SystemKind) => void;
};

export function StepType({ selected, onChange }: Props) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
      {CARDS.map(({ type, label, description, icon: Icon }) => {
        const isSelected = selected === type;
        return (
          <button
            key={type}
            type="button"
            onClick={() => onChange(type)}
            aria-pressed={isSelected}
            className={cn(
              "flex flex-col items-start gap-2 rounded-md border p-4 text-left transition-colors duration-150 ease-out",
              isSelected
                ? "border-primary bg-primary/5"
                : "border-border bg-card/30 hover:border-border-strong hover:bg-surface-raised",
            )}
          >
            <span
              className={cn(
                "flex h-8 w-8 items-center justify-center rounded-md",
                isSelected
                  ? "bg-primary/10 text-primary"
                  : "bg-muted text-muted-foreground",
              )}
            >
              <Icon className="h-4 w-4" />
            </span>
            <span className="text-body-strong">{label}</span>
            <span className="text-caption text-muted-foreground">{description}</span>
          </button>
        );
      })}
    </div>
  );
}
