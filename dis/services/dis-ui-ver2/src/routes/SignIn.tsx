import { useEffect } from 'react'

import { useAuth } from '../auth/useAuth'

// The PRODUCTION sign-in entry point. No persona picker and no dev imports: it fires the
// Auth0 login redirect (Auth0AuthProvider sends the browser to VITE_CM_LOGIN_URL) and shows a
// holding message for the moment before the navigation happens.
//
// THIS ROUTE EXISTS BECAUSE /dev/login USED TO DO THIS JOB. AuthBoundary sent unauthenticated
// users to /dev/login, which branched on isRealMode() and rendered exactly this component in
// real mode - so the production login path ran through a route whose module also imported the
// persona list and the stub signer. Splitting the real behaviour out is what let the dev route
// leave the production build (P1-SEC-001) without removing the ability to sign in.
export function SignIn() {
  const { status, login } = useAuth()

  useEffect(() => {
    // Mirrors AuthBoundary's loading gate: redirect ONLY once the Auth0 SDK has definitively
    // resolved to no session. During 'loading' an SSO handshake may still complete, and
    // redirecting then bounces an active session back to CM login.
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
