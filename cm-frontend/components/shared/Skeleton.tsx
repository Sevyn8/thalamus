import { cn } from "@/lib/utils";

export type SkeletonVariant = "card" | "row" | "rect" | "circle" | "text";

export type SkeletonProps = {
  variant: SkeletonVariant;
  count?: number;
  className?: string;
};

const VARIANT_CLASSES: Record<SkeletonVariant, string> = {
  card: "h-48 w-full rounded-md",
  row: "h-12 w-full rounded-md",
  rect: "h-24 w-full rounded-md",
  circle: "h-10 w-10 rounded-full",
  text: "h-4 w-full rounded",
};

function Bar({ className }: { className: string }) {
  return <div data-slot="skeleton" className={cn("skeleton-shimmer", className)} aria-hidden="true" />;
}

export function Skeleton({ variant, count = 1, className }: SkeletonProps) {
  const cls = cn(VARIANT_CLASSES[variant], className);
  if (count === 1) return <Bar className={cls} />;
  return (
    <div className="flex flex-col gap-3" aria-busy="true">
      {Array.from({ length: count }).map((_, i) => (
        <Bar key={i} className={cls} />
      ))}
    </div>
  );
}
