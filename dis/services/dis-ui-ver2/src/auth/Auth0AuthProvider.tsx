import { useAuth0 } from '@auth0/auth0-react'
import { decodeJwt } from 'jose'
import { useEffect, useMemo, useRef, useState } from 'react'
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
  const { isLoading, isAuthenticated, getAccessTokenSilently, loginWithRedirect, logout, error } =
    useAuth0()
  const [snapshot, setSnapshot] = useState<AuthSnapshot | null>(null)
  // The access token is fetched asynchronously after Auth0 reports authenticated;
  // until it is written to storage, client.ts would have no bearer, so we hold the
  // status at 'loading' (tokenReady=false) rather than prematurely 'authenticated'.
  const [tokenReady, setTokenReady] = useState(false)

  // Loop guard for the silent-authorize attempt below. Computed once per page load:
  // true when the URL carries an Auth0 redirect result (?code/?state on success,
  // ?error on prompt=none failure). When returning from a callback we must NOT fire
  // another authorize, or /callback would bounce back to /authorize forever.
  const returningFromCallback = useMemo(() => {
    if (typeof window === 'undefined') return false
    const params = new URLSearchParams(window.location.search)
    return params.has('code') || params.has('state') || params.has('error')
  }, [])
  // Fire the silent authorize at most once per load (a ref, so re-renders don't retry).
  const silentAuthAttempted = useRef(false)
  // Set only if loginWithRedirect fails to navigate; lets status settle to
  // 'unauthenticated' (-> /dev/login -> CM) instead of hanging on 'loading'.
  const [authorizeFailed, setAuthorizeFailed] = useState(false)

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

  // Single-login-entry: when the SDK has DEFINITIVELY resolved to no session, attempt
  // a silent (prompt=none) Auth0 authorize FIRST. If the CM-established SSO session
  // exists, Auth0 returns immediately with a code (no login UI), DIS lands on
  // /callback, gets its token, and renders — no CM bounce. If there is no session,
  // Auth0 returns ?error=login_required and Callback.tsx does the CM fallback.
  // Guards: skip while loading, already authenticated, an error is present, or we are
  // returning from a callback; and fire at most once per load (the ref).
  useEffect(() => {
    if (isLoading || isAuthenticated || error || returningFromCallback) return
    if (silentAuthAttempted.current) return
    silentAuthAttempted.current = true
    void loginWithRedirect({
      appState: { returnTo: window.location.pathname },
      authorizationParams: { prompt: 'none' },
    }).catch(() => {
      // Failed to even start the redirect: fall back to the normal unauthenticated
      // path (-> /dev/login -> CM) rather than hang on the loading placeholder.
      setAuthorizeFailed(true)
    })
  }, [isLoading, isAuthenticated, error, returningFromCallback, loginWithRedirect])

  // While the silent authorize is pending (unauthenticated, no error, not returning
  // from a callback, not failed), report 'loading' — NOT 'unauthenticated' — so
  // AuthBoundary shows its placeholder and never navigates to /dev/login before the
  // prompt=none redirect fires. Only a callback error / authorize failure surfaces
  // 'unauthenticated' (Callback handles login_required; the boundary handles the rest).
  const status: AuthStatus =
    isLoading || (isAuthenticated && !tokenReady)
      ? 'loading'
      : isAuthenticated
        ? 'authenticated'
        : error || returningFromCallback || authorizeFailed
          ? 'unauthenticated'
          : 'loading'

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      snapshot,
      // Customer Master (CM) is the single login entry point. This branch is only
      // reached with NO DIS session (an existing SSO session makes isAuthenticated
      // true, so the silent-token path above handles it without ever calling login).
      // Instead of DIS running its own interactive Auth0 login, redirect to CM's
      // login (which lands on My Cortex). The rawToken arg is ignored in real mode.
      async login() {
        window.location.href = import.meta.env.VITE_CM_LOGIN_URL ?? window.location.origin
      },
      logout() {
        clearToken()
        void logout({ logoutParams: { returnTo: window.location.origin } })
      },
    }),
    [status, snapshot, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
