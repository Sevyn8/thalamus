"use client";

import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export type KpiTone = "blue" | "purple" | "teal" | "green" | "orange" | "red";

const TONE_CLASSES: Record<KpiTone, string> = {
  blue: "bg-blue-50 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300",
  purple: "bg-violet-50 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300",
  teal: "bg-teal-50 text-teal-700 dark:bg-teal-500/15 dark:text-teal-300",
  green: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
  orange: "bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
  red: "bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300",
};

// Phase 5e.4: extended with `available` + `unavailableText` props.
// When `available: false`, the metric is replaced with the muted
// friendly text ("Coming soon" or unavailable_reason-mapped).
// Backend ships type-stable sentinels (e.g. value: 0) on stub cards
// per D-31 append-only — frontend MUST gate render on `available`,
// not on `value > 0`. When the stub flips to real, only the prop
// changes; render structure stays identical.
export type KpiCardProps = {
  icon: ReactNode;
  iconTone: KpiTone;
  metric: string;
  label: string;
  subtext?: string;
  delta?: string;
  // Defaults true for backwards-compat with any non-Phase-5e4
  // consumer; Phase 5e4 dashboard passes explicitly.
  available?: boolean;
  // Friendly-text shown in place of the metric when available=false.
  // Per ambiguity vi: hardcoded 3-key map at the call site, falls
  // back to raw enum on unknown values.
  unavailableText?: string;
  onClick?: () => void;
};

export function KpiCard({
  icon,
  iconTone,
  metric,
  label,
  subtext,
  delta,
  available = true,
  unavailableText,
  onClick,
}: KpiCardProps) {
  const interactive = !!onClick && available;
  const isUnavailable = available === false;

  return (
    <Card
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      onClick={interactive ? onClick : undefined}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick?.();
              }
            }
          : undefined
      }
      className={cn(
        "p-4 transition-colors",
        interactive
          ? "cursor-pointer hover:bg-accent/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
          : isUnavailable
            ? "opacity-70"
            : undefined,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wider text-muted-foreground">
            {label}
          </span>
          {isUnavailable ? (
            <span className="text-sm text-muted-foreground italic">
              {unavailableText ?? "Coming soon"}
            </span>
          ) : (
            <span className="text-display font-semibold">{metric}</span>
          )}
          {!isUnavailable && subtext ? (
            <span className="text-xs text-muted-foreground">{subtext}</span>
          ) : null}
          {!isUnavailable && delta ? (
            <span className="text-xs font-medium text-emerald-700 dark:text-emerald-400">
              {delta}
            </span>
          ) : null}
        </div>
        <span
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-md",
            TONE_CLASSES[iconTone],
            isUnavailable && "opacity-60",
          )}
          aria-hidden="true"
        >
          {icon}
        </span>
      </div>
    </Card>
  );
}
