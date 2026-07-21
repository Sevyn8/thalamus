// Identity-claim extraction from the Auth0 session user.
//
// The Auth0-issued token carries namespaced custom claims (stamped by the
// shared cortex-cm-claims Action); the SDK surfaces them on the session `user`
// object (useUser() client / auth0.getSession() server). The frontend reads
// only the four it needs, under the https://sevyn8.com/ namespace:
//
//   https://sevyn8.com/user_id    -> userId
//   https://sevyn8.com/user_type  -> userType (PLATFORM|TENANT)
//   https://sevyn8.com/tenant_id  -> tenantId (null for PLATFORM)
//   https://sevyn8.com/email      -> email
//
// No `name` claim; display name is derived from email (see persona-from-claims).
// This is UI hydration only; server-side enforcement (cm-backend RS256/JWKS
// verify) is the security boundary.

const CLAIM_PREFIX = "https://sevyn8.com/";

export type UserType = "PLATFORM" | "TENANT";

export type JwtClaims = {
  userId: string;
  userType: UserType;
  tenantId: string | null;
  email: string;
};

/**
 * Extract the four namespaced identity claims from the Auth0 session user
 * object. Returns null if a required claim is missing or malformed, so callers
 * render conservatively rather than trusting a partial identity.
 */
export function claimsFromSessionUser(
  user: Record<string, unknown> | null | undefined,
): JwtClaims | null {
  if (!user) return null;

  const userId = user[`${CLAIM_PREFIX}user_id`];
  const userType = user[`${CLAIM_PREFIX}user_type`];
  // PLATFORM users OMIT tenant_id entirely (vs returning null); normalize
  // undefined/null/missing to null to match the declared JwtClaims.tenantId.
  const tenantIdRaw = user[`${CLAIM_PREFIX}tenant_id`];
  const email = user[`${CLAIM_PREFIX}email`];

  if (typeof userId !== "string" || userId.length === 0) return null;
  if (userType !== "PLATFORM" && userType !== "TENANT") return null;
  if (typeof email !== "string" || email.length === 0) return null;
  if (
    tenantIdRaw !== null &&
    tenantIdRaw !== undefined &&
    typeof tenantIdRaw !== "string"
  ) {
    return null;
  }
  const tenantId: string | null =
    typeof tenantIdRaw === "string" ? tenantIdRaw : null;

  return { userId, userType, tenantId, email };
}
