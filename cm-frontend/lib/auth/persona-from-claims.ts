import type { JwtClaims } from "./jwt-decode";
import type { Persona, PersonaId } from "./personas";
import { findDevSeedById } from "./personas";

// Phase 5f.W.1: build a Persona from decoded JWT claims plus optional
// dev seed metadata. The seed is consulted ONLY when the active dev
// persona id matches a seed entry — its purpose is display-only (name
// + tenantName for the /dev/login UI and for surfaces that show a
// human-readable label). For real auth users, the display name is
// derived from the email local-part.

function deriveNameFromEmail(email: string): string {
  const local = email.split("@")[0] ?? "";
  if (local.length === 0) return "User";
  // Strip dots/hyphens/underscores; capitalize first character.
  // "a.kowalski" -> "A.kowalski" feels slightly odd; this is
  // intentionally minimal — real users get a /me/profile shipment
  // later that provides display_name properly.
  return local.charAt(0).toUpperCase() + local.slice(1);
}

export function buildPersonaFromClaims(
  claims: JwtClaims,
  devPersonaId: PersonaId | null,
): Persona {
  const seed = devPersonaId ? findDevSeedById(devPersonaId) : undefined;
  const name = seed ? seed.name : deriveNameFromEmail(claims.email);
  // tenantName: seed when present + tenant context matches; null
  // otherwise. PLATFORM personas have tenantId === null and seed
  // tenantName === null.
  const tenantName = seed && seed.tenantName ? seed.tenantName : null;
  return {
    userId: claims.userId,
    userType: claims.userType,
    tenantId: claims.tenantId,
    email: claims.email,
    name,
    tenantName,
    devPersonaId: seed ? seed.id : undefined,
  };
}
