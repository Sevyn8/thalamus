import type { AuthSnapshot } from '../../auth/AuthSnapshot'
import { PERSONAS } from '../../auth/dev/personas'
import type { StubPersona } from '../../auth/dev/personas'
import { ME_FIXTURES } from './fixtures'
import { getMe } from './me'

function toSnapshot(persona: StubPersona): AuthSnapshot {
  return {
    userId: persona.sub,
    tenantId: persona.tenant_id,
    storeId: persona.store_id,
    userType: persona.user_type,
    roles: persona.roles,
  }
}

const tenant = PERSONAS.find((p) => p.id === 'tenant')!
const ops = PERSONAS.find((p) => p.id === 'ops')!

describe('getMe (fixture mode)', () => {
  it('returns the tenant profile with tenant_name', async () => {
    const me = await getMe(toSnapshot(tenant))
    expect(me).toEqual({
      user_id: 'u_acmeuser0001',
      email: 'acme.user@example.test',
      name: 'A. Kowalski',
      tenant_id: 't_acme9k2l1mn4',
      tenant_name: 'Żabka Group',
    })
  })

  // Mirrors dis-ui's inconsistency (D37): the ops persona's sub is 'anjali', but ME_FIXTURES
  // has no 'anjali' key (its ops fixture is keyed 'u_opsdev0001'), so getMe(ops) throws.
  it('throws for the ops persona (sub anjali has no fixture; dis-ui D37 mismatch)', async () => {
    await expect(getMe(toSnapshot(ops))).rejects.toThrow(/no fixture/)
  })

  // The ops fixture that DOES exist is keyed 'u_opsdev0001' and maps to no persona.
  it('has an ops fixture keyed u_opsdev0001 with null tenant_id/name', () => {
    const opsFixture = ME_FIXTURES['u_opsdev0001']
    expect(opsFixture.user_id).toBe('u_opsdev0001')
    expect(opsFixture.tenant_id).toBeNull()
    expect(opsFixture.tenant_name).toBeNull()
  })

  it('rejects for a user with no fixture', async () => {
    const unknown: AuthSnapshot = { ...toSnapshot(tenant), userId: 'no-such-user' }
    await expect(getMe(unknown)).rejects.toThrow(/no fixture/)
  })
})

// Mirrors dis-ui EXACTLY: only the tenant persona's sub resolves a fixture; the ops persona's
// sub ('anjali') does NOT (the D37 sub/key mismatch, deliberately not reconciled).
describe('persona -> fixture keying (dis-ui-matched, incl. D37 gap)', () => {
  it('tenant persona sub resolves a fixture (profile tenant_id is the external display code, distinct from the token UUID)', () => {
    const fixture = ME_FIXTURES[tenant.sub]
    expect(fixture).toBeDefined()
    expect(fixture.user_id).toBe(tenant.sub)
    // The /me profile carries the external tenant DISPLAY code (a Customer Master concern);
    // the persona's tenant_id is now the internal RLS UUID the token claim carries (steps 6-7,
    // real mode). They are DELIBERATELY distinct (the D37 external<->UUID gap), so the profile
    // fixture is keyed/resolved by sub, not by the token's tenant UUID.
    expect(fixture.tenant_id).toBe('t_acme9k2l1mn4')
    expect(fixture.tenant_id).not.toBe(tenant.tenant_id)
  })

  it('ops persona sub does NOT resolve a fixture (D37)', () => {
    expect(ME_FIXTURES[ops.sub]).toBeUndefined()
  })
})
