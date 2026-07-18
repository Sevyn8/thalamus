import type { SelectHTMLAttributes } from 'react'

import { cn } from '@/lib/utils'

// v2 reskin of dis-ui's Select -> mockup .input. Caller supplies <option> children.
export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cn('input', className)} />
}
