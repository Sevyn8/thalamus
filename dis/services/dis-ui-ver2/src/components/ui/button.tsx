import type { ButtonHTMLAttributes } from 'react'

import { cn } from '@/lib/utils'

// v2 reskin of dis-ui's Button (same variant/size prop surface) mapped to the mockup .btn
// vocabulary. No cva, no icon lib. buttonVariants returns a class string for link-as-button use.
type Variant = 'default' | 'outline' | 'ghost' | 'destructive' | 'secondary' | 'link'
type Size = 'default' | 'sm' | 'xs' | 'icon' | 'icon-sm' | 'icon-lg'

const VARIANT: Record<Variant, string> = {
  default: 'btn pri',
  outline: 'btn',
  ghost: 'btn ghost',
  destructive: 'btn danger',
  secondary: 'btn',
  link: 'btn ghost',
}
const SIZE: Partial<Record<Size, string>> = { sm: 'sm', xs: 'sm', 'icon-sm': 'sm' }

export function buttonVariants(opts?: { variant?: Variant; size?: Size; className?: string }): string {
  const { variant = 'default', size = 'default', className } = opts ?? {}
  return cn(VARIANT[variant], SIZE[size], className)
}

export function Button({
  variant = 'default',
  size = 'default',
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
  return <button {...props} className={buttonVariants({ variant, size, className })} />
}
