import type { AuthSnapshot } from './AuthSnapshot'
import { isOps } from './AuthSnapshot'

// isOps keys on the token's user_type (the backend's read-scope discriminator), NOT on the
// dis:ops role. The load-bearing regression: dev tokens grant the full role set (incl. dis:ops)
// to TENANT users, yet the backend still pins their reads to the tenant — so a TENANT must NOT be
// treated as ops just because it carries dis:ops.
function snapshot(over: Partial<AuthSnapshot>): AuthSnapshot {
  return {
    userId: 'u',
    tenantId: 't_acme9k2l1mn4',
    storeId: null,
    userType: 'TENANT',
    roles: [],
    ...over,
  }
}

describe('isOps', () => {
  it('is true for a PLATFORM user_type', () => {
    expect(isOps(snapshot({ userType: 'PLATFORM', tenantId: null }))).toBe(true)
  })

  it('is false for a TENANT user_type', () => {
    expect(isOps(snapshot({ userType: 'TENANT' }))).toBe(false)
  })

  it('is false for a TENANT that ALSO carries the dis:ops role (does not key on roles)', () => {
    expect(isOps(snapshot({ userType: 'TENANT', roles: ['dis:ops', 'dis:read'] }))).toBe(false)
  })

  it('is false for a null user_type (absent/unrecognized claim)', () => {
    expect(isOps(snapshot({ userType: null, roles: ['dis:ops'] }))).toBe(false)
  })
})
