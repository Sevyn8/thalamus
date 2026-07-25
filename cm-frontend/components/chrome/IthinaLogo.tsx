import { cn } from "@/lib/utils";

// Phase 5d.7: shared Ithina brandmark. Three consumers at three
// sizes — Sidebar (32px), My Ithina launcher (48px), dev-login
// (64px). Constrained literal-union size prop resists
// over-generalization; if a 4th size lands, widen here.
//
// Slice 7 (item 8): renders the animated Sevyn8 mark
// (/public/sevyn8-mark-animated.svg, the convergence-loop brand
// asset) at all sizes, replacing the prior Cortex /logo.svg. The
// component keeps its internal name (IthinaLogo) — internal
// identifiers are not renamed. Visible on light + dark backgrounds.

export type IthinaLogoSize = 32 | 48 | 64;

export function IthinaLogo({
  size,
  className,
}: {
  size: IthinaLogoSize;
  className?: string;
}) {
  // next/image's optimization pipeline is a no-op for static SVG
  // (the SVG already serves at its viewBox dimensions); using
  // <img> avoids the runtime <Image> overhead for what's a single
  // static asset. Disable the lint rule with intent documented.
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src="/sevyn8-mark-animated.svg"
      alt="Sevyn8"
      width={size}
      height={size}
      className={cn("block shrink-0", className)}
    />
  );
}
