import { useAuth0 } from '@auth0/auth0-react'
import { decodeJwt } from 'jose'
import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import type { AuthSnapshot, UserType } from './AuthSnapshot'
import { AuthContext } from './context'
import type { AuthContextValue, AuthStatus } from './context'
import { clearToken, writeToken } from './storage'

// Real-mode (Auth0) auth provider. Adapts @auth0/auth0-react's useAuth0() to the
// EXISTING AuthContextValue contract ({status, snapshot, login, logout}), so
// useAuth() / AuthBoundary / every consumer and client.ts are byte-unchanged: the
// only difference from the stub AuthProvider is the token SOURCE (Auth0 SDK) and
// that it writes the access token into the SAME localStorage slot via writeToken()
// for client.ts to read. Selected at the app root by isRealMode(); the stub
// AuthProvider (persona picker + verifyToken) is untouched and used in fixture mode.

// Custom-claim namespace of the live Auth0 tenant (https://sevyn8.com), identical
// to Customer Master's and to the dis-ui-server verifier. Mirrors verifyToken.ts's
// toSnapshot claim mapping, reading the namespaced claim names (Auth0 access tokens
// only carry namespaced custom claims). This decode is ADVISORY (client-side, no
// signature check); the backend RS256/JWKS verifier is the real gate.
const NS = 'https://sevyn8.com'

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
}

function snapshotFromToken(token: string): AuthSnapshot {
  const claims = decodeJwt(token)
  const sub = typeof claims.sub === 'string' ? claims.sub : ''
  const rawTenant = claims[`${NS}/tenant_id`]
  const tenantId = rawTenant === null || rawTenant === undefined ? null : String(rawTenant)
  const rawStore = claims[`${NS}/store_id`]
  const storeId = rawStore === null || rawStore === undefined ? null : String(rawStore)
  const rawRoles = claims[`${NS}/roles`]
  const roles = isStringArray(rawRoles) ? rawRoles : []
  const rawType = claims[`${NS}/user_type`]
  const userType: UserType | null = rawType === 'TENANT' || rawType === 'PLATFORM' ? rawType : null
  return { userId: sub, tenantId, storeId, roles, userType }
}

export function Auth0AuthProvider({ children }: { children: ReactNode }) {
  const { isLoading, isAuthenticated, getAccessTokenSilently, loginWithRedirect, logout } = useAuth0()
  const [snapshot, setSnapshot] = useState<AuthSnapshot | null>(null)
  // The access token is fetched asynchronously after Auth0 reports authenticated;
  // until it is written to storage, client.ts would have no bearer, so we hold the
  // status at 'loading' (tokenReady=false) rather than prematurely 'authenticated'.
  const [tokenReady, setTokenReady] = useState(false)

  useEffect(() => {
    if (!isAuthenticated) {
      setSnapshot(null)
      setTokenReady(false)
      return
    }
    let active = true
    // Fetch the access token and write it into the SAME localStorage slot the stub
    // path uses, so client.ts (sessionToken -> readToken) is unchanged. Re-runs when
    // Auth0's auth state changes. Token-refresh-on-401 is a deferred refinement:
    // getAccessTokenSilently would be re-invoked on a 401 from dis-ui-server; that
    // wiring is out of scope for the built-not-wired step.
    getAccessTokenSilently()
      .then((token) => {
        if (!active) {
          return
        }
        writeToken(token)
        setSnapshot(snapshotFromToken(token))
        setTokenReady(true)
      })
      .catch(() => {
        if (!active) {
          return
        }
        clearToken()
        setSnapshot(null)
        setTokenReady(false)
      })
    return () => {
      active = false
    }
  }, [isAuthenticated, getAccessTokenSilently])

  const status: AuthStatus =
    isLoading || (isAuthenticated && !tokenReady)
      ? 'loading'
      : isAuthenticated
        ? 'authenticated'
        : 'unauthenticated'

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      snapshot,
      // In real mode the rawToken arg is ignored: sign-in is the Auth0 redirect flow.
      async login() {
        await loginWithRedirect()
      },
      logout() {
        clearToken()
        void logout({ logoutParams: { returnTo: window.location.origin } })
      },
    }),
    [status, snapshot, loginWithRedirect, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
