// Minimal className joiner (v2). dis-ui's cn is clsx+tailwind-merge; v2 uses plain design-system
// classes (no Tailwind-utility conflicts to merge), so a truthy-join is sufficient and adds no dep.
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ')
}
