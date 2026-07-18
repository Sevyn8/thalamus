import type { HTMLAttributes, ReactNode } from 'react'

import { cn } from '@/lib/utils'

// v2 reskin of dis-ui's Badge -> mockup .badge. Semantic tone classes are applied by callers
// (StatusBadge); the base is the neutral pill.
export function Badge({
  className,
  children,
  ...p
}: HTMLAttributes<HTMLSpanElement> & { children: ReactNode }) {
  return (
    <span {...p} className={cn('badge', className)}>
      {children}
    </span>
  )
}
