import type { Persona } from "@/lib/auth/personas";

// Phase 5c.1c stub for the dis.pii.view permission. Hardcoded to
// userType === "PLATFORM": Anjali (and any future Platform persona)
// can reveal raw PII; tenant personas (Kowalski) cannot.
//
// Real Roles & Permissions wiring lands in Phase 5e production
// cutover blockers. At that point this function reads from the
// effective-permissions catalog returned by Ithina's /superadmin/
// roles surface, and DIS pages no longer hardcode userType.

export function canViewRawPii(persona: Persona | null | undefined): boolean {
  return persona?.userType === "PLATFORM";
}
