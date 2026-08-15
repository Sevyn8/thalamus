import { useState } from 'react'
import { useNavigate } from 'react-router'

import { PERSONAS } from '../auth/dev/personas'
import { signStubToken } from '../auth/dev/signStubToken'
import { useAuth } from '../auth/useAuth'

// THE DEV PERSONA PICKER, SPLIT OUT OF DevLogin SO IT CAN BE EXCLUDED FROM A PRODUCTION BUILD.
//
// It used to be a branch inside DevLogin, which imported PERSONAS and signStubToken at the top
// level. Static imports cannot be tree-shaken while the importing module is reachable, and
// DevLogin is reachable in every mode because /dev/login is where AuthBoundary sends an
// unauthenticated user. So the dev-stub SECRET, the stub ISSUER and every persona identity were
// string literals in the shipped bundle: measured in the deployed v18 asset, fetched
// unauthenticated, one occurrence each.
//
// signStubToken's own `if (import.meta.env.PROD) throw` did not prevent that and could not. It
// stops OUR code from minting in production; it does nothing about somebody reading the secret
// out of the published JavaScript and minting a token themselves with any JWT library. The
// stub verifier would accept it and its claims would drive RLS.
//
// DevLogin now reaches this module only through a dynamic import gated on import.meta.env.PROD,
// which Vite replaces with a literal at build time, so Rollup folds the branch away and emits
// no chunk containing any of it. The gate is the BUILD flag rather than isRealMode(), because
// isRealMode() reads VITE_DIS_UI_SERVER_MODE, a DEPLOYMENT variable that can simply be absent;
// a production build made without it would ship the secret again. PROD cannot be absent from a
// production build.
//
// Nothing here is a behaviour change: the picker works exactly as it did in dev and in tests.
export default function DevPersonaPicker() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)

  async function pick(personaId: string): Promise<void> {
    setError(null)
    const persona = PERSONAS.find((candidate) => candidate.id === personaId)
    if (persona === undefined) {
      setError('Unknown persona')
      return
    }
    try {
      // Mint the persona's stub token at runtime (HMAC; secret/iss/aud match the
      // backend verifier). The claims - including the seeded tenant_id/store_id UUIDs
      // the RLS keys on - come straight from the persona, so no rebuild is needed to
      // change them.
      const token = await signStubToken(persona)
      await login(token)
      navigate('/', { replace: true })
    } catch {
      setError('Could not sign in with the selected persona')
    }
  }

  return (
    <section className="mx-auto mt-16 max-w-md px-4">
      <h1 className="mb-1 text-2xl font-semibold">DIS UI v2 - Dev Login</h1>
      <p className="mb-4 text-sm text-gray-500">
        Pick a persona to sign in with a local stub token.
      </p>
      <ul className="flex flex-col gap-3">
        {PERSONAS.map((persona) => (
          <li key={persona.id}>
            <button
              type="button"
              onClick={() => void pick(persona.id)}
              className="flex w-full flex-col items-start gap-1 rounded-md border border-gray-300 p-4 text-left hover:bg-gray-50"
            >
              <span className="text-base font-semibold">{persona.name}</span>
              <span className="text-sm text-gray-500">{persona.email}</span>
              <span className="mt-1 rounded bg-gray-100 px-2 py-0.5 text-xs font-medium">
                {persona.roleLabel}
                {persona.tenantName !== null ? ` - ${persona.tenantName}` : ''}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {error !== null ? (
        <p role="alert" className="mt-3 text-sm text-red-600">
          {error}
        </p>
      ) : null}
    </section>
  )
}
