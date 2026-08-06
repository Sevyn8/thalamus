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
  TENANT: "text-info",
  BUSINESS_UNIT: "text-[var(--magenta)]",
  HQ: "text-info",
  COUNTRY: "text-[var(--cyan)]",
  REGION: "text-success",
  STORE: "text-warning",
  DEPARTMENT: "text-foreground-muted dark:text-foreground-subtle",
};

export function OrgNodeTypeIcon({ type, className }: { type: OrgNodeType; className?: string }) {
  const Icon = ICON_BY_TYPE[type];
  return <Icon className={cn("h-4 w-4 shrink-0", TINT_BY_TYPE[type], className)} aria-hidden="true" />;
}
