import { Suspense, lazy, useEffect } from 'react'

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

// THE DEV PICKER IS REACHED ONLY THROUGH A DYNAMIC IMPORT THAT A PRODUCTION BUILD CANNOT
// REACH, and the shape of this line is the whole mechanism.
//
// import.meta.env.PROD is replaced by Vite with the literal `true` in a production build, so
// Rollup folds `true ? null : lazy(import(...))` to `null`, the import() becomes unreachable,
// and NO CHUNK IS EMITTED for DevPersonaPicker or anything it pulls in: the dev-stub secret,
// the stub issuer, and every persona identity. Those were all present as string literals in
// the deployed v18 bundle, measured rather than assumed.
//
// A STATIC IMPORT COULD NOT ACHIEVE THIS. DevLogin is reachable in every mode, because
// AuthBoundary sends unauthenticated users to /dev/login, so anything it imports statically
// ships. That is why the picker moved to its own module rather than staying a branch here.
//
// GATED ON THE BUILD FLAG, NOT ON isRealMode(). isRealMode() reads
// VITE_DIS_UI_SERVER_MODE, a deployment variable that can be absent, and a production build
// made without it would ship the secret again. PROD cannot be absent from a production build.
const DevPersonaPicker = import.meta.env.PROD
  ? null
  : lazy(() => import('./DevPersonaPicker'))

// /dev/login is LOAD-BEARING IN REAL MODE and this route is not going anywhere: AuthBoundary
// navigates here when the session resolves to unauthenticated, and RealModeSignIn is what
// fires the redirect to Customer Master's login. Only the dev branch above is excluded from a
// production build.
export function DevLogin() {
  // Production, or real mode in any build: the CM login redirect, never the picker.
  if (DevPersonaPicker === null || isRealMode()) {
    return <RealModeSignIn />
  }

  return (
    <Suspense fallback={<p className="mx-auto mt-16 max-w-md px-4 text-sm text-gray-500">Loading...</p>}>
      <DevPersonaPicker />
    </Suspense>
  )
}
