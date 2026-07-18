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
  GOAL_CONSOLE: "bg-violet-50 text-violet-700 ring-violet-200 dark:bg-violet-500/15 dark:text-violet-300 dark:ring-violet-500/30",
  PRICING_OS: "bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:ring-emerald-500/30",
  PERISHABLES_ASSISTANT: "bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-500/15 dark:text-amber-300 dark:ring-amber-500/30",
  PROMOTIONS_ASSISTANT: "bg-rose-50 text-rose-700 ring-rose-200 dark:bg-rose-500/15 dark:text-rose-300 dark:ring-rose-500/30",
  ADMIN: "bg-zinc-100 text-zinc-700 ring-zinc-300 dark:bg-zinc-500/15 dark:text-zinc-300 dark:ring-zinc-500/30",
  DIS: "bg-teal-50 text-teal-700 ring-teal-200 dark:bg-teal-500/15 dark:text-teal-300 dark:ring-teal-500/30",
};

export type ModuleSummaryCardProps = {
  module: ModuleCard;
  onClick: () => void;
};

// Phase 5e.3: rewritten to consume backend's ModuleCard shape.
// Tagline dropped — backend doesn't ship it; pre-5e.3 hand-fixture
// taglines became dev/prod skew once the wiring landed.
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
