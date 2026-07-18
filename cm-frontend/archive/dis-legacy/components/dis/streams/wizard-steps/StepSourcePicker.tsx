"use client";

import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { SystemKindChip } from "@/components/dis/chips/SystemKindChip";
import { useSources } from "@/lib/dis/hooks/use-sources";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { cn } from "@/lib/utils";
import type { Source } from "@/types/dis";

// Phase 5e.4d step 1 (when source not pre-bound via URL): pick the
// parent source. List scopes to the persona's tenant (TENANT auto-
// locked; PLATFORM sees all sources across tenants — same pattern
// as the Sources page in MSW mode). When the wizard is reached via
// /dis/streams/new?source={id}, this step is skipped automatically
// by the parent.

type Props = {
  selectedSourceId: string | null;
  onSelect: (source: Source) => void;
};

export function StepSourcePicker({ selectedSourceId, onSelect }: Props) {
  const snapshot = useAuthSnapshot();
  const tenantId = snapshot?.user.tenantId ?? undefined;
  const query = useSources(tenantId ? { tenant_id: tenantId } : undefined);

  if (query.isLoading) return <Skeleton variant="row" count={4} />;
  if (query.error) {
    return (
      <ErrorInline
        message="Could not load sources."
        onRetry={() => query.refetch()}
      />
    );
  }

  const sources = query.data?.items ?? [];
  if (sources.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border px-6 py-10 text-center">
        <p className="text-sm font-medium">No sources to pick from</p>
        <p className="text-caption text-muted-foreground">
          Add a source first via{" "}
          <span className="font-mono text-xs">/dis/sources/new</span>.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="text-caption text-muted-foreground">
        Pick the system identity this stream sources data from. Each
        feed (orders, inventory, customers, etc.) belongs to one source.
      </p>
      <ul className="flex flex-col rounded-md border border-border bg-card/30">
        {sources.map((s, i) => {
          const isSelected = selectedSourceId === s.id;
          return (
            <li
              key={s.id}
              className={cn(
                i > 0 ? "border-t border-border" : "",
              )}
            >
              <button
                type="button"
                onClick={() => onSelect(s)}
                aria-pressed={isSelected}
                className={cn(
                  "flex w-full items-center gap-3 px-4 py-3 text-left transition-colors duration-150 ease-out",
                  isSelected
                    ? "bg-primary/5"
                    : "hover:bg-surface-raised",
                )}
              >
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate text-body-strong">{s.name}</span>
                  <span className="truncate text-caption text-muted-foreground">
                    {s.tenant_name}
                    {s.org_node_code ? ` · ${s.org_node_code}` : ""}
                  </span>
                </span>
                <SystemKindChip type={s.type} />
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
