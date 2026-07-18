// Phase 5n.4 (2026-05-18): minimal honest empty state for surfaces
// whose backend hasn't shipped yet. Internal users only; short
// half-life (Admin APIs ~2 days, DIS APIs ~15 days). When the
// corresponding backend ships, replace the FeaturePending stub with
// the real hook + render path; do NOT keep mock data structures
// around for design refinement.

interface FeaturePendingProps {
  surface: string;
  eta?: string;
}

export function FeaturePending({ surface, eta }: FeaturePendingProps) {
  return (
    <div className="flex min-h-[300px] flex-col items-center justify-center gap-2 px-6 text-center">
      <div className="text-sm font-medium text-muted-foreground">
        {surface}
      </div>
      <div className="text-xs text-muted-foreground/70">
        Backend integration in progress{eta ? ` (${eta})` : ""}
      </div>
    </div>
  );
}
