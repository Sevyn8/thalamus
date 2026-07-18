import type { ReactNode } from 'react'

// Reusable empty state, v2 design vocabulary (.empty). Mirrors dis-ui's EmptyState API
// (title/message/children) so ported surfaces call it identically; only the look differs.
export function EmptyState({
  title,
  message,
  children,
}: {
  title: string
  message?: string
  children?: ReactNode
}) {
  return (
    <div className="empty">
      <h4>{title}</h4>
      {message !== undefined ? <div>{message}</div> : null}
      {children}
    </div>
  )
}
