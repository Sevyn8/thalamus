// Minimal honest empty state for surfaces whose backend hasn't shipped
// yet. Internal users only. When the corresponding backend ships,
// replace the FeaturePending stub with the real hook + render path; do
// NOT keep mock data structures around for design refinement.

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
