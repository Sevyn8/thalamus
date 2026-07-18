// Single source of truth for design tokens.
// Mirrors the values declared in app/globals.css.
// Use this for non-Tailwind consumers (chart colors, manual style props).

export const TYPOGRAPHY = {
  display:    { fontSize: 24, lineHeight: 32, fontWeight: 600 },
  heading:    { fontSize: 18, lineHeight: 24, fontWeight: 600 },
  subheading: { fontSize: 15, lineHeight: 22, fontWeight: 600 },
  body:       { fontSize: 14, lineHeight: 20, fontWeight: 400 },
  bodyStrong: { fontSize: 14, lineHeight: 20, fontWeight: 500 },
  caption:    { fontSize: 13, lineHeight: 18, fontWeight: 400 },
  label:      { fontSize: 12, lineHeight: 16, fontWeight: 500, textTransform: "uppercase", letterSpacing: "0.05em" },
  micro:      { fontSize: 11, lineHeight: 14, fontWeight: 400 },
} as const;

export const SPACING = {
  page:      24,  // p-6   page outer
  section:   24,  // gap-6 between sections
  card:      16,  // p-4   card internal
  cardGap:   12,  // gap-3 inside-card
  row:       12,  // py-3  table row
  formField: 16,  // gap-4 form field stack
  inline:    8,   // gap-2 icon + label
} as const;

export const RADIUS = {
  sm:      2,
  default: 4,
  md:      6,
} as const;

export const COLORS = {
  background:        "var(--background)",
  foreground:        "var(--foreground)",
  foregroundMuted:   "var(--foreground-muted)",
  foregroundSubtle:  "var(--foreground-subtle)",
  surface:           "var(--surface)",
  surfaceRaised:     "var(--surface-raised)",
  border:            "var(--border)",
  borderStrong:      "var(--border-strong)",
  primary:           "var(--primary)",
  primaryForeground: "var(--primary-foreground)",
  success:           "var(--success)",
  warning:           "var(--warning)",
  danger:            "var(--danger)",
  info:              "var(--info)",
} as const;
