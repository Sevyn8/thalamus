import { SignJWT } from 'jose'

import { STUB_AUDIENCE, STUB_ISSUER, STUB_SECRET } from './dev/devStubSecret'
import { PERSONAS } from './dev/personas'
import { TokenInvalidError, verifyToken } from './verifyToken'

const KEY = new TextEncoder().encode(STUB_SECRET)

type Claims = {
  sub?: string
  tenant_id?: unknown
  store_id?: unknown
  user_type?: unknown
  roles?: unknown
}

// Local signer so tests can control expiry and omit/misshape claims (signStubToken
// always produces a valid, fresh token, which only covers the happy path).
async function sign(claims: Claims, expiration: string | number = '8h'): Promise<string> {
  const { sub, ...rest } = claims
  const builder = new SignJWT(rest as Record<string, unknown>)
    .setProtectedHeader({ alg: 'HS256' })
    .setIssuedAt()
    .setIssuer(STUB_ISSUER)
    .setAudience(STUB_AUDIENCE)
    .setExpirationTime(expiration)
  if (sub !== undefined) {
    builder.setSubject(sub)
  }
  return builder.sign(KEY)
}

const tenant = PERSONAS[0]

describe('verifyToken', () => {
  it('returns a snapshot for a valid token, mapping the user_type claim', async () => {
    const token = await sign({
      sub: tenant.sub,
      tenant_id: tenant.tenant_id,
      store_id: tenant.store_id,
      user_type: tenant.user_type,
      roles: tenant.roles,
    })
    const snapshot = await verifyToken(token)
    expect(snapshot).toEqual({
      userId: tenant.sub,
      tenantId: tenant.tenant_id,
      storeId: tenant.store_id,
      userType: 'TENANT',
      roles: tenant.roles,
    })
  })

  it('accepts a null tenant_id and store_id (ops, cross-tenant) and maps PLATFORM', async () => {
    const token = await sign({
      sub: 'u_opsdev0001',
      tenant_id: null,
      store_id: null,
      user_type: 'PLATFORM',
      roles: ['dis:ops'],
    })
    const snapshot = await verifyToken(token)
    expect(snapshot.tenantId).toBeNull()
    expect(snapshot.storeId).toBeNull()
    expect(snapshot.userType).toBe('PLATFORM')
    expect(snapshot.roles).toEqual(['dis:ops'])
  })

  it('maps an absent or unrecognized user_type claim to null (trusts, does not enforce)', async () => {
    const noClaim = await sign({ sub: 'u_x', tenant_id: 't_x', store_id: null, roles: ['dis:read'] })
    expect((await verifyToken(noClaim)).userType).toBeNull()

    const bad = await sign({ sub: 'u_y', tenant_id: 't_y', store_id: null, user_type: 'ADMIN', roles: [] })
    expect((await verifyToken(bad)).userType).toBeNull()
  })

  it('rejects a malformed token', async () => {
    await expect(verifyToken('not-a-jwt')).rejects.toBeInstanceOf(TokenInvalidError)
    await expect(verifyToken('not-a-jwt')).rejects.toMatchObject({ reason: 'malformed' })
  })

  it('rejects an expired token', async () => {
    const past = Math.floor(Date.now() / 1000) - 60
    const token = await sign(
      { sub: tenant.sub, tenant_id: tenant.tenant_id, store_id: tenant.store_id, roles: tenant.roles },
      past,
    )
    await expect(verifyToken(token)).rejects.toMatchObject({ reason: 'expired' })
  })

  it('rejects a token with missing or invalid claims', async () => {
    const noSub = await sign({ tenant_id: 't_x', store_id: null, roles: ['dis:read'] })
    await expect(verifyToken(noSub)).rejects.toMatchObject({ reason: 'invalid-claims' })

    const badRoles = await sign({ sub: 'u_x', tenant_id: 't_x', store_id: null, roles: 'dis:read' })
    await expect(verifyToken(badRoles)).rejects.toMatchObject({ reason: 'invalid-claims' })
  })
})
