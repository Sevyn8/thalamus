import { SignJWT } from 'jose'

import type { StubPersona } from './personas'
import { STUB_AUDIENCE, STUB_EXPIRY, STUB_ISSUER, STUB_SECRET } from './devStubSecret'

const KEY = new TextEncoder().encode(STUB_SECRET)

// DEV ONLY. Mints a local HMAC-signed stub JWT for a persona, carrying the Customer Master
// claim set (sub via setSubject, plus tenant_id / store_id / user_type / roles). No profile
// claims (email/name) - those are not token claims. The verify path (verifyToken.ts) is the
// seam that later swaps HMAC for JWKS.
//
// THE import.meta.env.PROD THROW BELOW IS NOT THE CONTROL, AND BELIEVING IT WAS IS WHAT LET
// this module ship publicly for months. It stops this FUNCTION running in a production build;
// it does nothing about the signing key sitting in the emitted JavaScript for anyone to sign
// with. The control is that a production build has no import path to this module at all
// (vite.config.ts's @devAuthSeam alias) and that scripts/assert-no-dev-auth.mjs fails the
// build if the key reaches dist/ anyway. This check is kept as a second line, not the first.
export async function signStubToken(persona: StubPersona): Promise<string> {
  if (import.meta.env.PROD) {
    throw new Error('signStubToken is dev-only and must not run in a production build')
  }

  return new SignJWT({
    tenant_id: persona.tenant_id,
    store_id: persona.store_id,
    user_type: persona.user_type,
    roles: persona.roles,
  })
    .setProtectedHeader({ alg: 'HS256' })
    .setSubject(persona.sub)
    .setIssuedAt()
    .setIssuer(STUB_ISSUER)
    .setAudience(STUB_AUDIENCE)
    .setExpirationTime(STUB_EXPIRY)
    .sign(KEY)
}
