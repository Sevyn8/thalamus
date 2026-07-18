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

// Phase 5c.2a: 9-type icon + label mapping. Brand iconography for the
// named POS connectors (Square, Lightspeed, Shopify POS, Toast, Clover)
// is intentionally NOT shipped — pending legal review on trademark use.
// All 5 named connectors use a generic lucide Plug icon plus their
// brand text as the label. Brand SVGs land post-legal-clear, likely
// Phase 5e or later (tracked as a known-deferred item in BUILD_PLAN).

const TYPE_META: Record<SystemKind, { icon: LucideIcon; label: string }> = {
  CSV_SCHEDULED: { icon: FileSpreadsheet, label: "CSV (scheduled)" },
  SQUARE: { icon: Plug, label: "Square" },
  LIGHTSPEED: { icon: Plug, label: "Lightspeed" },
  SHOPIFY_POS: { icon: Plug, label: "Shopify POS" },
  TOAST: { icon: Plug, label: "Toast" },
  CLOVER: { icon: Plug, label: "Clover" },
  POS_API_GENERIC: { icon: Globe, label: "POS API (generic)" },
  FTP: { icon: Server, label: "FTP" },
  REST_API_GENERIC: { icon: Code, label: "REST API (generic)" },
};

export function SystemKindChip({
  type,
  className,
}: {
  type: SystemKind;
  className?: string;
}) {
  const { icon: Icon, label } = TYPE_META[type];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium",
        "bg-zinc-100 text-zinc-700 ring-1 ring-inset ring-zinc-300",
        "dark:bg-zinc-500/15 dark:text-zinc-300 dark:ring-zinc-500/30",
        className,
      )}
    >
      <Icon className="h-3 w-3" />
      {label}
    </span>
  );
}
