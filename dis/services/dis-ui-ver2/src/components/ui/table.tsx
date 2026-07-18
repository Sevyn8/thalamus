import type { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from 'react'

import { cn } from '@/lib/utils'

// v2 reskin of dis-ui's Table family -> mockup table.tbl vocabulary.
export function Table({ className, ...p }: HTMLAttributes<HTMLTableElement>) {
  return (
    <div style={{ overflow: 'auto' }}>
      <table {...p} className={cn('tbl', className)} />
    </div>
  )
}
export function TableHeader({ ...p }: HTMLAttributes<HTMLTableSectionElement>) {
  return <thead {...p} />
}
export function TableBody({ ...p }: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody {...p} />
}
export function TableRow({ className, ...p }: HTMLAttributes<HTMLTableRowElement>) {
  return <tr {...p} className={className} />
}
export function TableHead({ className, ...p }: ThHTMLAttributes<HTMLTableCellElement>) {
  return <th {...p} className={className} />
}
export function TableCell({ className, ...p }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td {...p} className={className} />
}
