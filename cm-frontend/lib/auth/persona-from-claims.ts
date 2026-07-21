import type { JwtClaims } from "./jwt-decode";
import type { Persona } from "./personas";

// Build a Persona from the session's identity claims. Display name is derived
// from the email local-part (a proper display_name arrives via /me profile
// later); tenantName is null here (the tenant display label is resolved from
// the module-access matrix on the launcher, not from the token).

function deriveNameFromEmail(email: string): string {
  const local = email.split("@")[0] ?? "";
  if (local.length === 0) return "User";
  return local.charAt(0).toUpperCase() + local.slice(1);
}

export function buildPersonaFromClaims(claims: JwtClaims): Persona {
  return {
    userId: claims.userId,
    userType: claims.userType,
    tenantId: claims.tenantId,
    email: claims.email,
    name: deriveNameFromEmail(claims.email),
    tenantName: null,
  };
}
