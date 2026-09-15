import { Navigate, Outlet } from 'react-router'

import { signInPath } from '@devAuthSeam'
import { useAuth } from './useAuth'

// Gates protected routes. The branch ORDER here is load-bearing — 'loading' MUST be
// handled before any redirect decision:
//   - 'loading'         The Auth0 SDK is still resolving the session (SSO handshake /
//                       silent token fetch). Render a placeholder and WAIT. Never make
//                       an auth-based redirect in this window, or an active SSO session
//                       gets bounced to sign-in (and on to CM login) before it
//                       resolves — the single-login-entry race.
//   - 'unauthenticated' SDK definitively resolved with no session -> signInPath, which the
//                       build-time seam sets to /signin in production (fires the Auth0
//                       redirect to CM login) and /dev/login in dev builds (the persona
//                       picker). It was a hardcoded /dev/login until P1-SEC-001 made that
//                       route dev-only; the literal would otherwise still ship.
//   - 'authenticated'   session present -> render the protected tree.
// isLoading always settles to authenticated or unauthenticated, so the placeholder is
// never terminal (no infinite spinner).
export function AuthBoundary() {
  const { status } = useAuth()

  if (status === 'loading') {
    return <p className="mx-auto mt-16 max-w-md px-4 text-sm text-gray-500">Loading...</p>
  }
  if (status === 'unauthenticated') {
    return <Navigate to={signInPath} replace />
  }
  return <Outlet />
}
