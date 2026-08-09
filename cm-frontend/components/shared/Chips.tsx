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

// dis-ui-ver2's badge vocabulary. ver2 defines six status classes (.b-ok/.b-warn/.b-fail/
// .b-info/.b-live/.b-mut, index.css:548-577) and each sets a TRIPLE — foreground, background
// and border together. A status colour is never used alone there, which is why the tokens come
// in threes.
//
// ONE RECIPE, NOT TWO. The old chip carried a light recipe plus a dark: override on every tone.
// Both themes now resolve through the same semantic tokens, so the dark variants are gone and
// the chip cannot drift between modes.
//
// TWO TONES HAVE NO ver2 EQUIVALENT. `violet` and `purple` exist for org-node categories, which
// ver2 has no palette for. Derived from ver2's spectrum accents rather than sourced elsewhere:
// --magenta (index.css:26) for both, distinguished by fill weight. Flagged in the design spec.
const TONE_CLASSES: Record<Tone, string> = {
  green: "bg-[var(--success-bg)] text-success ring-[var(--success-line)]",
  amber: "bg-[var(--warning-bg)] text-warning ring-[var(--warning-line)]",
  red: "bg-[var(--danger-bg)] text-danger ring-[var(--danger-line)]",
  blue: "bg-[var(--info-bg)] text-info ring-[var(--info-line)]",
  teal: "bg-[color-mix(in_srgb,var(--cyan)_12%,transparent)] text-[var(--cyan)] ring-[color-mix(in_srgb,var(--cyan)_30%,transparent)]",
  violet:
    "bg-[color-mix(in_srgb,var(--magenta)_12%,transparent)] text-[var(--magenta)] ring-[color-mix(in_srgb,var(--magenta)_30%,transparent)]",
  purple:
    "bg-[color-mix(in_srgb,var(--magenta)_18%,transparent)] text-[var(--magenta)] ring-[color-mix(in_srgb,var(--magenta)_40%,transparent)]",
  grey: "bg-muted text-foreground-muted ring-border",
};

// `dot` IS ADDITIVE AND DEFAULTS TO TRUE, so every existing call site renders exactly what it
// rendered before. It exists because the Synapse console mockups draw a status pill with a
// border and NO leading dot, and the dot is the one part of this recipe that carries no
// information: the tone already says the same thing in colour. Opting out per call site rather
// than forking the recipe keeps one source of truth for what a chip looks like.
export function Chip({
  tone,
  children,
  className,
  dot = true,
}: {
  tone: Tone;
  children: ReactNode;
  className?: string;
  dot?: boolean;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset",
        TONE_CLASSES[tone],
        className,
      )}
    >
      {dot ? (
        <span aria-hidden="true" className={cn("h-1.5 w-1.5 rounded-full", DOT_CLASSES[tone])} />
      ) : null}
      {children}
    </span>
  );
}

const DOT_CLASSES: Record<Tone, string> = {
  green: "bg-success",
  amber: "bg-warning",
  red: "bg-danger",
  blue: "bg-info",
  teal: "bg-[var(--cyan)]",
  violet: "bg-[var(--magenta)]",
  purple: "bg-[var(--magenta)]",
  grey: "bg-foreground-subtle",
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
