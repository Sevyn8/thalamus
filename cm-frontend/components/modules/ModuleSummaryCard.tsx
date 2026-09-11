"use client";

import {
  Apple,
  Database,
  DollarSign,
  Megaphone,
  Settings,
  Target,
} from "lucide-react";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { ModuleCard, ModuleCode } from "@/types/api";

const ICON_BY_CODE: Record<
  ModuleCode,
  React.ComponentType<{ className?: string }>
> = {
  GOAL_CONSOLE: Target,
  PRICING_OS: DollarSign,
  PERISHABLES_ASSISTANT: Apple,
  PROMOTIONS_ASSISTANT: Megaphone,
  ADMIN: Settings,
  DIS: Database,
};

const TONE_BY_CODE: Record<ModuleCode, string> = {
  GOAL_CONSOLE: "bg-[color-mix(in_srgb,var(--magenta)_12%,transparent)] text-[var(--magenta)] ring-[color-mix(in_srgb,var(--magenta)_30%,transparent)]",
  PRICING_OS: "bg-[var(--success-bg)] text-success ring-[var(--success-line)] dark:bg-success/15",
  PERISHABLES_ASSISTANT: "bg-[var(--warning-bg)] text-warning ring-[var(--warning-line)] dark:bg-warning/15",
  PROMOTIONS_ASSISTANT: "bg-rose-50 text-rose-700 ring-rose-200 dark:bg-rose-500/15 dark:text-rose-300 dark:ring-rose-500/30",
  ADMIN: "bg-muted text-foreground-muted ring-border",
  DIS: "bg-[color-mix(in_srgb,var(--cyan)_12%,transparent)] text-[var(--cyan)] ring-[color-mix(in_srgb,var(--cyan)_30%,transparent)]",
};

export type ModuleSummaryCardProps = {
  module: ModuleCard;
  onClick: () => void;
};

// Consumes backend's ModuleCard shape. Tagline dropped — backend
// doesn't ship it.
export function ModuleSummaryCard({ module, onClick }: ModuleSummaryCardProps) {
  const Icon = ICON_BY_CODE[module.module_code];
  return (
    <Card
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
      className="cursor-pointer transition-colors hover:bg-accent/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
    >
      <CardHeader className="flex flex-row items-start gap-3">
        <span
          className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-md ring-1 ring-inset",
            TONE_BY_CODE[module.module_code],
          )}
          aria-hidden="true"
        >
          <Icon className="h-5 w-5" />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <div className="truncate text-sm font-semibold">{module.module_label}</div>
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-xs text-muted-foreground">
          Enabled in{" "}
          <span className="font-medium text-foreground">
            {module.enabled_count}
          </span>{" "}
          / {module.total_active_trial_tenants} tenants
        </p>
      </CardContent>
    </Card>
  );
}
