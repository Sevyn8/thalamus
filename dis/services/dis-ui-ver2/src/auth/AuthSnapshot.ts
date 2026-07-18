// The in-memory identity + authz for the signed-in user, derived purely by
// decoding the auth token's claims (see verifyToken.ts). It mirrors the Customer
// Master token model that Sanjeev's slice-2 fakes pin (PROVISIONAL, pending D25):
// sub + tenant_id + store_id + user_type + a roles list. It carries NO profile fields
// (email, name, tenant_name) - those are not token claims; they come from the separate
// dis-ui-server GET /me profile call (see lib/dis-ui-server/types.ts MeResponse).

// The token's user_type claim (Slice 17b, D91): the backend's AUTHORITATIVE
// tenant-vs-ops discriminator. TENANT scopes to its own tenant; PLATFORM is cross-tenant.
export type UserType = 'TENANT' | 'PLATFORM'

export type AuthSnapshot = {
  userId: string
  // null for PLATFORM users, who are cross-tenant; a concrete tenant for TENANT users.
  tenantId: string | null
  storeId: string | null
  // Role strings from the token, e.g. dis:upload / dis:read / dis:ops /
  // dis:mapping_admin. Vocabulary is PROVISIONAL pending decisions.md D25.
  roles: string[]
  // The verified `user_type` claim. null when the token omits it or carries an
  // unrecognized value: the frontend TRUSTS the claim but does not enforce
  // user_type<->tenant_id coherence (the backend verifier does, per D91).
  userType: UserType | null
}

// The only tenant-vs-ops gate for Phase 1. Ops surfaces require this; everything
// else is tenant-default. Keys on `user_type` — the backend's own read-scope
// discriminator (auth/scope.py require_read_scope) — NOT on the `dis:ops` role: a
// TENANT token may legitimately carry dis:ops (dev tokens grant the full role set)
// while the backend still pins its reads to the tenant, so role-based gating would
// wrongly expose cross-tenant/ops surfaces. No fine-grained permission gating exists
// yet (D25 open).
export function isOps(snapshot: AuthSnapshot): boolean {
  return snapshot.userType === 'PLATFORM'
}
