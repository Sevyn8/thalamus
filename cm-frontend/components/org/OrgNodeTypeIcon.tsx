"use client";

import { Briefcase, Building2, Folder, Globe, Landmark, MapPin, Store } from "lucide-react";

import { cn } from "@/lib/utils";
import type { OrgNodeType } from "@/types/api";

const ICON_BY_TYPE: Record<OrgNodeType, React.ComponentType<{ className?: string }>> = {
  TENANT: Building2,
  BUSINESS_UNIT: Briefcase,
  HQ: Landmark,
  COUNTRY: Globe,
  REGION: MapPin,
  STORE: Store,
  DEPARTMENT: Folder,
};

const TINT_BY_TYPE: Record<OrgNodeType, string> = {
  TENANT: "text-blue-700 dark:text-blue-300",
  BUSINESS_UNIT: "text-violet-700 dark:text-violet-300",
  HQ: "text-blue-700 dark:text-blue-300",
  COUNTRY: "text-teal-700 dark:text-teal-300",
  REGION: "text-emerald-700 dark:text-emerald-300",
  STORE: "text-amber-700 dark:text-amber-300",
  DEPARTMENT: "text-zinc-600 dark:text-zinc-400",
};

export function OrgNodeTypeIcon({ type, className }: { type: OrgNodeType; className?: string }) {
  const Icon = ICON_BY_TYPE[type];
  return <Icon className={cn("h-4 w-4 shrink-0", TINT_BY_TYPE[type], className)} aria-hidden="true" />;
}
