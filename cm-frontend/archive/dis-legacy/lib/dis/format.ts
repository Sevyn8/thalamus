// Phase 5c.8e2: shared DIS formatting helpers. Extracted from
// inline duplicates across:
//   - app/(dis-authenticated)/dis/admin/llm-ops/page.tsx
//   - app/(dis-authenticated)/dis/admin/llm-ops/[tenant_id]/page.tsx
//   - app/(dis-authenticated)/dis/dashboards/page.tsx
// at the third-consumer threshold per the two-consumer-then-lift
// policy. Cost page (5c.8e2) is the fourth consumer.

// Dual-decimal USD formatter:
//   $X.XXXX  when usd  < 1   (small cents-and-fractions matter)
//   $X.XX    when usd >= 1   (typical retail dollar amounts)
// The $1.00 boundary uses the 2-decimal form per ambiguity xiii
// from 5c.8c (>= threshold = 2-decimal).
export function formatCost(usd: number): string {
  if (usd >= 1) return `$${usd.toFixed(2)}`;
  return `$${usd.toFixed(4)}`;
}

// Humanize token counts: 12.4K / 1.2M. Edges: < 1000 → exact;
// < 1M → "X.XK"; otherwise "X.XM". Trim trailing ".0".
// Currently inlined in LLM ops + dashboards pages too; lift on
// next consumer (TimeWindowTabs lift remains pending until a
// genuine third TimeWindow consumer arrives — humanizeTokens has
// only 2 consumers, so it stays inline for now). Documented here
// so the lift-trigger is visible.
