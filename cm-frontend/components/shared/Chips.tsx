import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import type {
  AuditResult,
  OrgNodeStatus,
  PermissionAction,
  PermissionScope,
  PlatformUserStatus,
  TenantStatus,
  TenantTier,
} from "@/types/api";

// Exported in Phase 5b.3 so DIS can build domain-specific chips
// (RunStatus, StreamHealth, AlertSeverity, FreshnessState, ValidationResult,
// DriftSeverity, etc.) by composing the base Chip with its own tone tables.
// Existing Ithina typed wrappers below (StatusChip, TierChip, ResultChip,
// ActionChip, ScopeChip) are unchanged.
export type Tone = "green" | "amber" | "red" | "blue" | "violet" | "teal" | "purple" | "grey";

// Light recipe (base classes) + dark: overrides. Light uses solid -50 bgs
// + -700 text + -200 ring; dark uses tinted alpha overlays. Same chip,
// two visually-equivalent recipes per theme.
const TONE_CLASSES: Record<Tone, string> = {
  green:
    "bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:ring-emerald-500/30",
  amber:
    "bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-500/15 dark:text-amber-300 dark:ring-amber-500/30",
  red:
    "bg-red-50 text-red-700 ring-red-200 dark:bg-red-500/15 dark:text-red-300 dark:ring-red-500/30",
  blue:
    "bg-blue-50 text-blue-700 ring-blue-200 dark:bg-blue-500/15 dark:text-blue-300 dark:ring-blue-500/30",
  violet:
    "bg-violet-50 text-violet-700 ring-violet-200 dark:bg-violet-500/15 dark:text-violet-300 dark:ring-violet-500/30",
  teal:
    "bg-teal-50 text-teal-700 ring-teal-200 dark:bg-teal-500/15 dark:text-teal-300 dark:ring-teal-500/30",
  purple:
    "bg-fuchsia-50 text-fuchsia-700 ring-fuchsia-200 dark:bg-fuchsia-500/15 dark:text-fuchsia-300 dark:ring-fuchsia-500/30",
  grey:
    "bg-zinc-100 text-zinc-700 ring-zinc-300 dark:bg-zinc-500/15 dark:text-zinc-300 dark:ring-zinc-500/30",
};

export function Chip({
  tone,
  children,
  className,
}: {
  tone: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        TONE_CLASSES[tone],
        className,
      )}
    >
      <span aria-hidden="true" className={cn("h-1.5 w-1.5 rounded-full", DOT_CLASSES[tone])} />
      {children}
    </span>
  );
}

const DOT_CLASSES: Record<Tone, string> = {
  green: "bg-emerald-600 dark:bg-emerald-400",
  amber: "bg-amber-600 dark:bg-amber-400",
  red: "bg-red-600 dark:bg-red-400",
  blue: "bg-blue-600 dark:bg-blue-400",
  violet: "bg-violet-600 dark:bg-violet-400",
  teal: "bg-teal-600 dark:bg-teal-400",
  purple: "bg-fuchsia-600 dark:bg-fuchsia-400",
  grey: "bg-zinc-500 dark:bg-zinc-400",
};

// PlatformUserStatus and TenantUserStatus have identical values
// (INVITED | ACTIVE | SUSPENDED), so PlatformUserStatus alone covers
// both user audiences in the union. StoreStatus adds OPENING +
// CLOSED on top of the existing ACTIVE/INACTIVE values it shares
// with other audiences (Phase 5-stores 2026-05-18).
type AnyStatus =
  | TenantStatus
  | PlatformUserStatus
  | OrgNodeStatus
  | "OPENING"
  | "CLOSED";

const STATUS_TONE: Record<AnyStatus, Tone> = {
  ACTIVE: "green",
  ONBOARDING: "blue",
  TRIAL: "amber",
  INVITED: "blue",
  SUSPENDED: "red",
  TERMINATED: "red",
  ARCHIVED: "grey",
  INACTIVE: "grey",
  OPENING: "blue",
  CLOSED: "grey",
};

const STATUS_LABEL: Record<AnyStatus, string> = {
  ACTIVE: "Active",
  ONBOARDING: "Onboarding",
  TRIAL: "Trial",
  INVITED: "Invited",
  SUSPENDED: "Suspended",
  TERMINATED: "Terminated",
  ARCHIVED: "Archived",
  INACTIVE: "Inactive",
  OPENING: "Opening",
  CLOSED: "Closed",
};

export function StatusChip({ status }: { status: AnyStatus }) {
  return <Chip tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</Chip>;
}

const TIER_TONE: Record<TenantTier, Tone> = {
  ENTERPRISE: "blue",
  MID_MARKET: "violet",
  SMB: "teal",
  SINGLE_STORE: "grey",
};

const TIER_LABEL: Record<TenantTier, string> = {
  ENTERPRISE: "Enterprise",
  MID_MARKET: "Mid-Market",
  SMB: "SMB",
  SINGLE_STORE: "Single-Store",
};

export function TierChip({ tier }: { tier: TenantTier }) {
  return <Chip tone={TIER_TONE[tier]}>{TIER_LABEL[tier]}</Chip>;
}

const RESULT_TONE: Record<AuditResult, Tone> = {
  SUCCESS: "green",
  PENDING: "amber",
  DENIED: "red",
};

const RESULT_LABEL: Record<AuditResult, string> = {
  SUCCESS: "Success",
  PENDING: "Pending",
  DENIED: "Denied",
};

export function ResultChip({ result }: { result: AuditResult }) {
  return <Chip tone={RESULT_TONE[result]}>{RESULT_LABEL[result]}</Chip>;
}

const ACTION_TONE: Record<PermissionAction, Tone> = {
  VIEW: "grey",
  CONFIGURE: "blue",
  EXECUTE: "teal",
  APPROVE: "green",
  OVERRIDE: "red",
  AUDIT: "purple",
};

export function ActionChip({ action }: { action: PermissionAction }) {
  return <Chip tone={ACTION_TONE[action]}>{action}</Chip>;
}

const SCOPE_LABEL: Record<PermissionScope, string> = {
  GLOBAL: "Global",
  TENANT: "Tenant",
  STORE: "Store",
};

export function ScopeChip({ scope }: { scope: PermissionScope }) {
  return <Chip tone="grey">{SCOPE_LABEL[scope]}</Chip>;
}
