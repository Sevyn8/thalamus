// JWT claim extraction for Phase 5f.W.1 Auth Phase 1 integration.
//
// Sanjeev's deployed-backend JWTs carry Auth0-style namespaced custom
// claims (per FN-AB-22 Auth0 expansion + decoded live JWT
// verification 2026-05-15). Standard claims (sub/iss/aud/iat/exp)
// also present but the frontend reads only what it needs:
//
//   https://ithina.com/user_id    -> Persona.userId
//   https://ithina.com/user_type  -> Persona.userType (PLATFORM|TENANT)
//   https://ithina.com/tenant_id  -> Persona.tenantId (null for PLATFORM)
//   https://ithina.com/email      -> Persona.email
//
// No `name` claim — display name is frontend-derived (dev seed or
// email-fallback per Phase 5f.W.1 ambiguity-2 resolution).
//
// This decode is for UI hydration only. Server-side enforcement is
// still the security boundary (per docs/endpoints/me.md). Tampering
// with the JWT in localStorage produces invalid signatures that the
// backend rejects at 401; the frontend's decode is forgiving (no
// signature verification) because invalid-signature JWTs surface as
// 401s on the first apiFetch.

const CLAIM_PREFIX = "https://ithina.com/";

export type UserType = "PLATFORM" | "TENANT";

export type JwtClaims = {
  userId: string;
  userType: UserType;
  tenantId: string | null;
  email: string;
};

/**
 * Decode the JWT payload segment and extract the 4 Auth0-namespaced
 * claims the frontend needs. Returns null if the token shape is
 * malformed, the payload is non-JSON, the required claims are
 * missing, or the user_type claim has an unexpected value.
 *
 * No signature verification — that's the backend's job. The frontend
 * trusts the claims for UI hydration only. Invalid signatures fail
 * at the first apiFetch (401 from backend's middleware).
 */
export function decodeJwtClaims(token: string | null): JwtClaims | null {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(atob(parts[1]!.replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return null;
  }

  const userId = payload[`${CLAIM_PREFIX}user_id`];
  const userType = payload[`${CLAIM_PREFIX}user_type`];
  // Phase 5f.W.1 fix: PLATFORM JWTs OMIT the tenant_id claim entirely
  // (vs returning null). Normalize undefined/null/missing-key at the
  // source so downstream code sees `string | null` matching the
  // declared JwtClaims.tenantId type.
  const tenantIdRaw = payload[`${CLAIM_PREFIX}tenant_id`];
  const email = payload[`${CLAIM_PREFIX}email`];

  if (typeof userId !== "string" || userId.length === 0) return null;
  if (userType !== "PLATFORM" && userType !== "TENANT") return null;
  if (typeof email !== "string" || email.length === 0) return null;
  // tenantId is allowed to be null/undefined/absent (PLATFORM
  // personas) or a string (TENANT personas). Anything else is
  // malformed.
  if (
    tenantIdRaw !== null &&
    tenantIdRaw !== undefined &&
    typeof tenantIdRaw !== "string"
  ) {
    return null;
  }
  const tenantId: string | null =
    typeof tenantIdRaw === "string" ? tenantIdRaw : null;

  return {
    userId,
    userType,
    tenantId,
    email,
  };
}
