import { Navigate, Outlet } from 'react-router'

import { useAuth } from './useAuth'

// Gates protected routes. The branch ORDER here is load-bearing — 'loading' MUST be
// handled before any redirect decision:
//   - 'loading'         The Auth0 SDK is still resolving the session (SSO handshake /
//                       silent token fetch). Render a placeholder and WAIT. Never make
//                       an auth-based redirect in this window, or an active SSO session
//                       gets bounced to /dev/login (and on to CM login) before it
//                       resolves — the single-login-entry race.
//   - 'unauthenticated' SDK definitively resolved with no session -> /dev/login, which
//                       in real mode redirects to CM login.
//   - 'authenticated'   session present -> render the protected tree.
// isLoading always settles to authenticated or unauthenticated, so the placeholder is
// never terminal (no infinite spinner).
export function AuthBoundary() {
  const { status } = useAuth()

  if (status === 'loading') {
    return <p className="mx-auto mt-16 max-w-md px-4 text-sm text-gray-500">Loading...</p>
  }
  if (status === 'unauthenticated') {
    return <Navigate to="/dev/login" replace />
  }
  return <Outlet />
}
