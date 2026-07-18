import type { InputHTMLAttributes } from 'react'

import { cn } from '@/lib/utils'

// v2 reskin of dis-ui's Input -> mockup .input.
export function Input({ className, ...p }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...p} className={cn('input', className)} />
}
