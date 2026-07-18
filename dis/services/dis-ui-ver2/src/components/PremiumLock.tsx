import type { ReactNode } from 'react'

// A small monochrome padlock drawn inline (no icon library). `currentColor` so callers tint it
// via CSS; used both in the nav (muted, next to a locked label) and in the PremiumLock banner.
export function LockGlyph({ size = 13 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="4" y="10.5" width="16" height="10" rx="2" />
      <path d="M8 10.5V7a4 4 0 0 1 8 0v3.5" />
    </svg>
  )
}

// Premium-feature wrapper — the single, shared place a real entitlement check would later gate on
// (one component, three uses). Two variants:
//
//   'fade'    (A) — render the REAL children beneath a faded treatment + the lock banner. VISUAL
//                   ONLY: never blocks rendering or fetching, so the wrapped surface's live fetch
//                   still fires and its data still renders under the fade (Connector Health).
//   'replace' (B) — the lock REPLACES the content: render ONLY the lock message. Children are NOT
//                   rendered (they are never passed in for B), so no body renders and — because the
//                   page mounts no data hooks in this branch — no backend fetch fires (Schema Drift,
//                   Credentials).
export function PremiumLock({
  title,
  variant = 'fade',
  children,
}: {
  title?: string
  variant?: 'fade' | 'replace'
  children?: ReactNode
}) {
  const banner = (
    <div className="premium-lock__banner" role="note">
      <span className="premium-lock__glyph">
        <LockGlyph size={15} />
      </span>
      <span>
        <b>{title ?? 'Premium feature'}</b> — available on a higher plan.
      </span>
    </div>
  )
  if (variant === 'replace') {
    // B: lock message in place of the content — no children rendered, no fetch.
    return <div className="premium-lock">{banner}</div>
  }
  // A: faded real content beneath the lock.
  return (
    <div className="premium-lock">
      {banner}
      <div className="premium-lock__content">{children}</div>
    </div>
  )
}
