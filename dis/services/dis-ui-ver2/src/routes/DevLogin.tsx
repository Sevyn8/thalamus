import { useState } from 'react'
import { useNavigate } from 'react-router'

import { PERSONAS } from '../auth/dev/personas'
import { useAuth } from '../auth/useAuth'

// Dev-only login. Logs in the chosen persona with its PRE-SUPPLIED dev-stub token
// (baked at build via VITE_STUB_TOKEN_* build args), hands it to AuthProvider via
// login(), and navigates to the protected home. No client-side minting and no real
// Customer Master here; this route is dev/staging only. Token handling (the persona
// -> pre-supplied token -> login() flow) mirrors services/dis-ui verbatim; only the
// presentation is a minimal local adaptation (no design-system primitives copied).
export function DevLogin() {
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
    // Per-persona pre-supplied dev-stub tokens, baked at build time via VITE_ build
    // args (literal import.meta.env accesses so Vite statically replaces them). No
    // client-side minting: each persona logs in with its own pre-supplied token.
    const PERSONA_TOKENS: Record<string, string | undefined> = {
      tenant: import.meta.env.VITE_STUB_TOKEN_TENANT,
      ops: import.meta.env.VITE_STUB_TOKEN_OPS,
    }
    const token = PERSONA_TOKENS[persona.id]
    if (token === undefined || token === '') {
      setError('Could not sign in with the selected persona')
      return
    }
    try {
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
