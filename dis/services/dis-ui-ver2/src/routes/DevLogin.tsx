import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'

import { PERSONAS } from '../auth/dev/personas'
import { signStubToken } from '../auth/dev/signStubToken'
import { useAuth } from '../auth/useAuth'
import { isRealMode } from '../lib/dis-ui-server/mode'

// Real mode (Auth0): no persona picker. Auto-fire the login() redirect (which
// Auth0AuthProvider wires to the CM login URL); the rawToken arg is ignored in real
// mode. Shown only for the moment before redirect.
function RealModeSignIn() {
  const { status, login } = useAuth()
  useEffect(() => {
    // Defense-in-depth, mirroring AuthBoundary's loading gate: fire the CM-login
    // redirect ONLY once the Auth0 SDK has definitively resolved to no session.
    // During 'loading' the SSO handshake may still complete into an authenticated
    // session; redirecting then would bounce an active session to CM login.
    if (status === 'unauthenticated') {
      void login('')
    }
  }, [status, login])
  return (
    <section className="mx-auto mt-16 max-w-md px-4">
      <p className="text-sm text-gray-500">Redirecting to sign in...</p>
    </section>
  )
}

// Dev-only login. Mints the chosen persona's dev-stub token AT RUNTIME via
// signStubToken (HMAC, byte-identical secret/iss/aud to the backend verifier), hands
// it to AuthProvider via login(), and navigates to the protected home. Runtime minting
// (rather than baking tokens into the bundle at build time) means the token always carries
// the persona's current claims - notably the real seeded tenant_id/store_id UUIDs the
// backend RLS keys on - so real mode against a live BFF authorizes correctly without a
// rebuild. signStubToken refuses to run in a production bundle. Dev/staging only.
export function DevLogin() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)

  // Real mode: skip the persona picker and auto-redirect to Auth0 sign-in.
  if (isRealMode()) {
    return <RealModeSignIn />
  }

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
