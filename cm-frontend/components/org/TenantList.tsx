"use client";

import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { cn } from "@/lib/utils";
import type { Tenant } from "@/types/api";

export type TenantListItem = Pick<Tenant, "id" | "name" | "display_code">;

export type TenantListProps = {
  tenants: TenantListItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  loading: boolean;
  onRetry?: () => void;
  hasError: boolean;
};

// Phase 4e: backend's tenants list (used here in place of the
// retired /api/v1/org-summary) doesn't carry node_count, so the
// previous "(N nodes)" badge per tile drops. The OrgTreePane's
// header already shows the per-tenant node total once a tenant is
// selected, so the information isn't lost — just relocated.
export function TenantList({
  tenants,
  selectedId,
  onSelect,
  loading,
  onRetry,
  hasError,
}: TenantListProps) {
  return (
    <aside className="flex h-fit flex-col gap-2 rounded-md border border-border bg-card/30 p-3">
      <div className="px-2 pt-1 text-label text-muted-foreground">
        Tenants
      </div>
      {loading ? (
        <Skeleton variant="row" count={7} />
      ) : hasError ? (
        <ErrorInline message="Could not load tenants." onRetry={onRetry} />
      ) : (
        <ul className="flex flex-col gap-0.5">
          {tenants.map((t) => {
            const selected = t.id === selectedId;
            return (
              <li key={t.id}>
                <button
                  type="button"
                  onClick={() => onSelect(t.id)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors",
                    selected ? "bg-accent text-foreground" : "text-foreground/80 hover:bg-accent/40",
                  )}
                  aria-pressed={selected}
                >
                  <span className="truncate">{t.name}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </aside>
  );
}
