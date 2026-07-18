"use client";

import { cn } from "@/lib/utils";
import type { OrgNodeType } from "@/types/api";

const RECIPE_BY_TYPE: Record<OrgNodeType, string> = {
  TENANT: "bg-blue-50 text-blue-700 ring-blue-200 dark:bg-blue-500/15 dark:text-blue-300 dark:ring-blue-500/30",
  BUSINESS_UNIT: "bg-violet-50 text-violet-700 ring-violet-200 dark:bg-violet-500/15 dark:text-violet-300 dark:ring-violet-500/30",
  HQ: "bg-blue-50 text-blue-700 ring-blue-200 dark:bg-blue-500/15 dark:text-blue-300 dark:ring-blue-500/30",
  COUNTRY: "bg-teal-50 text-teal-700 ring-teal-200 dark:bg-teal-500/15 dark:text-teal-300 dark:ring-teal-500/30",
  REGION: "bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:ring-emerald-500/30",
  STORE: "bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-500/15 dark:text-amber-300 dark:ring-amber-500/30",
  DEPARTMENT: "bg-zinc-100 text-zinc-700 ring-zinc-300 dark:bg-zinc-500/15 dark:text-zinc-300 dark:ring-zinc-500/30",
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
