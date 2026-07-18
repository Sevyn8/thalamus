import type { Persona } from "@/lib/auth/personas";

// Phase 5d.9: launcher welcome polish helpers. Pure functions
// (no hooks, no React); product-agnostic so they live at the
// cross-product lib/format/ level rather than lib/dis/ or
// lib/launcher/.
//
// Time staleness during long sessions: greeting is computed at
// render time. If the user keeps the launcher open across a
// boundary (e.g., 4:55pm → 5:05pm), the prefix stays stale until
// reload. Accepted trade-off for v1 — welcome polish is not
// load-bearing UX; adding a boundary-tick refresh would be ~15
// LOC of complexity for marginal benefit.

export type TimeOfDayGreeting =
  | "Good morning"
  | "Good afternoon"
  | "Good evening";

// Browser-local time boundaries:
//   5-11   → morning
//   12-16  → afternoon
//   17-4   → evening (wraps midnight: 17-23 and 0-4 both evening)
export function getTimeOfDayGreeting(now: Date): TimeOfDayGreeting {
  const h = now.getHours();
  if (h >= 5 && h < 12) return "Good morning";
  if (h >= 12 && h < 17) return "Good afternoon";
  return "Good evening";
}

// First-name extraction with fallback chain for awkward edge
// cases (e.g., "A. Kowalski" where the first token is an
// initial):
//   1. Take first whitespace token of name.
//   2. If first token is just an initial (ends in `.` or is ≤2
//      chars), fall back to the full name.
//   3. If name is empty, use email local-part (before `@`).
//   4. If neither available, return null — caller omits the
//      ", {name}" comma clause.
//
// Resolves: "Anjali Mehta" → "Anjali", "Kira Yilmaz" → "Kira",
// "A. Kowalski" → "A. Kowalski" (full kept), "" + "x@y.com" → "x".
export function getFirstName(persona: Persona): string | null {
  const name = persona.name.trim();
  if (name.length > 0) {
    const firstToken = name.split(/\s+/)[0] ?? "";
    const isInitial = firstToken.endsWith(".") || firstToken.length <= 2;
    return isInitial ? name : firstToken;
  }
  const email = persona.email.trim();
  if (email.length > 0) {
    const local = email.split("@")[0] ?? "";
    return local.length > 0 ? local : null;
  }
  return null;
}
