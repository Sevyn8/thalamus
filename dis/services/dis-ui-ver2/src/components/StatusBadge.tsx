import type { ReactNode } from 'react'

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

// v2 reskin of dis-ui's StatusBadge: maps a semantic tone to the mockup badge classes
// (.b-ok/.b-warn/.b-fail/.b-info/.b-mut). Same API (tone + children) so ported callers are verbatim.
export type StatusTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'

const TONE_CLASS: Record<StatusTone, string> = {
  success: 'b-ok',
  warning: 'b-warn',
  danger: 'b-fail',
  info: 'b-info',
  neutral: 'b-mut',
}

export function StatusBadge({
  tone,
  className,
  children,
}: {
  tone: StatusTone
  className?: string
  children: ReactNode
}) {
  return <Badge className={cn(TONE_CLASS[tone], className)}>{children}</Badge>
}
