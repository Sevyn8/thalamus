import type { UserType } from "./jwt-decode";

export type { UserType };

// Stable ID for the dev-login persona switcher and the auth cookie /
// localStorage. Phase 5f.W.1: this is a DEV-ONLY identifier, distinct
// from the canonical user_id that comes from the JWT claim.
export type PersonaId = "anjali" | "kira" | "kowalski";

// Canonical persona id set. Source of truth for runtime validation in
// getAuthToken, AuthBoundary, and the /api/dev-token route.
export const PERSONA_IDS = ["anjali", "kira", "kowalski"] as const;

export function isPersonaId(value: unknown): value is PersonaId {
  return (
    typeof value === "string" &&
    (PERSONA_IDS as readonly string[]).includes(value)
  );
}

// Phase 5f.W.1 Persona is JWT-derived. Catalogue (DevPersonaSeed
// below) is dev-only display metadata for the /dev/login switcher;
// the source of truth for userId/userType/tenantId/email at runtime
// is the JWT claims (decoded via lib/auth/jwt-decode.ts).
export type Persona = {
  // From JWT claims (https://ithina.com/{user_id,user_type,tenant_id,email})
  userId: string;
  userType: UserType;
  tenantId: string | null;
  email: string;
  // Frontend-derived: dev seed name when devPersonaId is set;
  // capitalize(email.split('@')[0]) fallback for real auth users.
  name: string;
  // From dev seed when matched by tenantId; null for PLATFORM
  // personas or real auth users without a seed-side display name.
  tenantName: string | null;
  // Set when the active JWT's user_id matches a dev seed entry.
  // Used by /dev/login UI; never load-bearing for production code.
  devPersonaId?: PersonaId;
};

// Dev-only display metadata for the /dev/login persona switcher.
// Strictly UI metadata — not the source of truth for runtime auth
// decisions. The JWT claim is what populates Persona at runtime.
// The userType field below is for the switcher's orienting badge
// only; runtime userType comes from the JWT.
export type DevPersonaSeed = {
  id: PersonaId;
  name: string;
  email: string;
  userType: UserType;
  tenantName: string | null;
  // True when a real cloud JWT exists for this persona; controls
  // which switcher cards are clickable. Kira has no entry in the
  // runtime DEV_JWT_MAP, so /api/dev-token returns null for her.
  hasRealJwt: boolean;
};

export const DEV_PERSONA_SEEDS: DevPersonaSeed[] = [
  {
    id: "anjali",
    name: "Anjali Mehta",
    email: "anjali@ithina.ai",
    userType: "PLATFORM",
    tenantName: null,
    hasRealJwt: true,
  },
  {
    id: "kira",
    name: "Kira Yilmaz",
    email: "kira@ithina.ai",
    userType: "PLATFORM",
    tenantName: null,
    hasRealJwt: false,
  },
  {
    id: "kowalski",
    name: "A. Kowalski",
    email: "a.kowalski@zabka.pl",
    userType: "TENANT",
    tenantName: "Żabka Group",
    hasRealJwt: true,
  },
];

export function findDevSeedById(id: string): DevPersonaSeed | undefined {
  return DEV_PERSONA_SEEDS.find((p) => p.id === id);
}
