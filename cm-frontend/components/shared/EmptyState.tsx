import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type EmptyStateProps = {
  title: string;
  body?: string;
  icon?: ReactNode;
  action?: { label: string; onClick: () => void };
  className?: string;
};

export function EmptyState({ title, body, icon, action, className }: EmptyStateProps) {
  return (
    <div
      role="status"
      className={cn(
        "mx-auto flex max-w-md flex-col items-center justify-center gap-3 rounded-md border border-dashed border-border px-6 py-12 text-center",
        className,
      )}
    >
      {icon ? <div className="text-muted-foreground [&>svg]:h-10 [&>svg]:w-10">{icon}</div> : null}
      <h3 className="text-base font-medium">{title}</h3>
      {body ? <p className="text-sm text-muted-foreground">{body}</p> : null}
      {action ? (
        <Button onClick={action.onClick} className="mt-2">
          {action.label}
        </Button>
      ) : null}
    </div>
  );
}
