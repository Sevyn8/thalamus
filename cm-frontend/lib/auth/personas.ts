import type { UserType } from "./jwt-decode";

export type { UserType };

// The identity the UI renders, built from the Auth0 session claims
// (buildPersonaFromClaims). Sourced from the token only; no dev-persona
// catalogue. tenantName is a display label resolved elsewhere (launcher
// matrix), null at construction.
export type Persona = {
  userId: string;
  userType: UserType;
  tenantId: string | null;
  email: string;
  // Frontend-derived display name (email local-part until /me profile ships).
  name: string;
  // Display label; null unless resolved by a consumer (e.g. the launcher).
  tenantName: string | null;
};
