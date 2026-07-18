"use client";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { StatusChip } from "@/components/shared/Chips";
import { initials, avatarTone } from "@/lib/utils/initials";
import { cn } from "@/lib/utils";
import type { Store } from "@/types/api";

export type StoreCardProps = {
  store: Store;
  onSelect: () => void;
};

export function StoreCard({ store, onSelect }: StoreCardProps) {
  return (
    <Card
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className="cursor-pointer transition-colors duration-150 ease-out hover:bg-surface-raised hover:border-border-strong"
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <span
              className={cn(
                "flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-sm font-semibold",
                avatarTone(store.name),
              )}
              aria-hidden="true"
            >
              {initials(store.name)}
            </span>
            <div className="flex min-w-0 flex-col">
              <div className="truncate text-subheading">{store.name}</div>
              <div className="truncate text-caption text-muted-foreground">
                {store.tenant_name}
              </div>
            </div>
          </div>
          <StatusChip status={store.status} />
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-1 pt-0 text-caption text-muted-foreground">
        <div className="flex items-center justify-between">
          <span>Country</span>
          <span className="text-foreground">{store.country}</span>
        </div>
        <div className="flex items-center justify-between">
          <span>Store code</span>
          <span className="font-mono text-foreground">
            {store.store_code ?? "—"}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
