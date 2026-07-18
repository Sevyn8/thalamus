"use client";

import { Button } from "@/components/ui/button";
import { comingInV1 } from "./ComingInV1Toast";

export type PageHeaderProps = {
  title: string;
  subtitle?: string;
  primaryAction?: { label: string; onClick?: () => void };
  rightSlot?: React.ReactNode;
};

export function PageHeader({ title, subtitle, primaryAction, rightSlot }: PageHeaderProps) {
  return (
    <div className="flex flex-col gap-2 border-b border-border px-6 py-6 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-col gap-1">
        <h1 className="text-display">{title}</h1>
        {subtitle ? <p className="text-caption text-foreground-muted">{subtitle}</p> : null}
      </div>
      <div className="flex items-center gap-3">
        {rightSlot}
        {primaryAction ? (
          <Button
            onClick={primaryAction.onClick ?? (() => comingInV1(primaryAction.label))}
          >
            {primaryAction.label}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
