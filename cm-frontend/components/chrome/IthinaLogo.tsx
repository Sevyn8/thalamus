import { cn } from "@/lib/utils";

// Phase 5d.7: shared Ithina brandmark. Three consumers at three
// sizes — Sidebar (32px), My Ithina launcher (48px), dev-login
// (64px). Constrained literal-union size prop resists
// over-generalization; if a 4th size lands, widen here.
//
// SVG asset at /public/logo.svg carries a hardcoded brand-blue
// fill (#2C4CFD). Visible on both light + dark backgrounds; no
// currentColor plumbing. If brand later wants a theme-aware
// variant, add /public/logo-dark.svg + theme-conditional src
// here.

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
      src="/logo.svg"
      alt="Cortex"
      width={size}
      height={size}
      className={cn("block shrink-0", className)}
    />
  );
}
