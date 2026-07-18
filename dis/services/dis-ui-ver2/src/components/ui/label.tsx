import type { LabelHTMLAttributes, ReactNode } from 'react'

// Minimal form label in v2's vocabulary (dis-ui Label API: htmlFor + children).
export function Label({
  children,
  ...props
}: LabelHTMLAttributes<HTMLLabelElement> & { children: ReactNode }) {
  return (
    <label {...props} style={{ display: 'block', fontSize: 12.5, fontWeight: 500, marginBottom: 6 }}>
      {children}
    </label>
  )
}
