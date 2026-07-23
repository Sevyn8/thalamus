import { useAuth0 } from '@auth0/auth0-react'
import { useEffect } from 'react'

// The prompt=none silent authorize (Auth0AuthProvider) returns here. When there is
// no shared SSO session, Auth0 responds with error=login_required (or
// interaction_required) — the genuine-logged-out case. Detect exactly that and treat
// it as the single-login-entry fallback: redirect to CM login (-> My Cortex).
function isNoSessionError(error: Error | undefined): boolean {
  if (!error) return false
  const code = (error as unknown as { error?: string }).error
  if (code === 'login_required' || code === 'interaction_required') return true
  return /login_required|interaction_required/.test(error.message ?? '')
}

// The Auth0 redirect target (redirect_uri = <origin>/callback). @auth0/auth0-react
// processes the ?code&state on load and then fires onRedirectCallback (App.tsx),
// which navigates to the intended route, so this typically renders only for a
// moment. A public route (like /dev/login), outside AuthBoundary.
export function Callback() {
  const { error } = useAuth0()
  const noSession = isNoSessionError(error)

  useEffect(() => {
    if (noSession) {
      // prompt=none found no session: genuinely logged out. Fall back to the single
      // login entry point (CM login -> My Cortex). This runs at most once — a full
      // page navigation away from /callback, so it cannot loop back into authorize.
      window.location.href = import.meta.env.VITE_CM_LOGIN_URL ?? window.location.origin
    }
  }, [noSession])

  // A real sign-in failure (not the no-session case) surfaces the error and does NOT
  // redirect, so a persistent error can never become a CM/authorize loop.
  if (error && !noSession) {
    return (
      <section className="mx-auto mt-16 max-w-md px-4">
        <p role="alert" className="text-sm text-red-600">
          Sign-in failed: {error.message}
        </p>
      </section>
    )
  }
  return (
    <section className="mx-auto mt-16 max-w-md px-4">
      <p className="text-sm text-gray-500">Signing in...</p>
    </section>
  )
}
