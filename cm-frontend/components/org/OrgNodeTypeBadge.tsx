"use client";

import { cn } from "@/lib/utils";
import type { OrgNodeType } from "@/types/api";

const RECIPE_BY_TYPE: Record<OrgNodeType, string> = {
  TENANT: "bg-[var(--info-bg)] text-info ring-[var(--info-line)] dark:bg-info/15",
  BUSINESS_UNIT: "bg-[color-mix(in_srgb,var(--magenta)_12%,transparent)] text-[var(--magenta)] ring-[color-mix(in_srgb,var(--magenta)_30%,transparent)]",
  HQ: "bg-[var(--info-bg)] text-info ring-[var(--info-line)] dark:bg-info/15",
  COUNTRY: "bg-[color-mix(in_srgb,var(--cyan)_12%,transparent)] text-[var(--cyan)] ring-[color-mix(in_srgb,var(--cyan)_30%,transparent)]",
  REGION: "bg-[var(--success-bg)] text-success ring-[var(--success-line)] dark:bg-success/15",
  STORE: "bg-[var(--warning-bg)] text-warning ring-[var(--warning-line)] dark:bg-warning/15",
  DEPARTMENT: "bg-muted text-foreground-muted ring-border",
};

const LABEL_BY_TYPE: Record<OrgNodeType, string> = {
  TENANT: "Tenant",
  BUSINESS_UNIT: "BU",
  HQ: "HQ",
  COUNTRY: "Country",
  REGION: "Region",
  STORE: "Store",
  DEPARTMENT: "Dept",
};

export function OrgNodeTypeBadge({ type }: { type: OrgNodeType }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-md px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ring-1 ring-inset",
        RECIPE_BY_TYPE[type],
      )}
    >
      {LABEL_BY_TYPE[type]}
    </span>
  );
}
