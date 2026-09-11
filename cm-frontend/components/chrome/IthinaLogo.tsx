import { cn } from "@/lib/utils";

// Shared Ithina brandmark. Two live consumers — Sidebar (32px) and
// My Sevyn8 launcher (48px). Constrained literal-union size prop
// resists over-generalization; if a 4th size lands, widen here.
//
// Renders the completed animated Sevyn8 mark
// (/public/sevyn8-mark-motion.svg, the convergence-loop brand
// asset with a self-contained CSS comet animation; spectrum
// gradient and geometry are the brand asset's verbatim, and it
// falls back to the static spectrum rendering under
// prefers-reduced-motion). Replaces the prior broken
// sevyn8-mark-animated.svg, which shipped no <style> and rendered
// as a black blob. The component keeps its internal name
// (IthinaLogo) — internal identifiers are not renamed. The
// spectrum stroke reads on both light and dark sidebars.

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
      src="/sevyn8-mark-motion.svg"
      alt="Sevyn8"
      width={size}
      height={size}
      className={cn("block shrink-0", className)}
    />
  );
}
