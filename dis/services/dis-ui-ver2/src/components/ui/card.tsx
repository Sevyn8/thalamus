import type { HTMLAttributes } from 'react'

import { cn } from '@/lib/utils'

// v2 reskin of dis-ui's Card family -> mockup .card / .hd / .bd.
export function Card({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div {...p} className={cn('card', className)} />
}
export function CardHeader({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div {...p} className={cn('hd', className)} />
}
export function CardTitle({ className, ...p }: HTMLAttributes<HTMLHeadingElement>) {
  return <h3 {...p} className={className} />
}
export function CardContent({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div {...p} className={cn('bd', className)} />
}
