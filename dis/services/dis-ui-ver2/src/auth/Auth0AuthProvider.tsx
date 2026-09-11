import { useAuth0 } from '@auth0/auth0-react'
import { decodeJwt } from 'jose'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import type { AuthSnapshot, UserType } from './AuthSnapshot'
import { AuthContext } from './context'
import type { AuthContextValue, AuthStatus, UserProfile } from './context'
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
  const {
    isLoading,
    isAuthenticated,
    user,
    getAccessTokenSilently,
    loginWithRedirect,
    logout,
    error,
  } = useAuth0()
  // ONE AUTHENTICATED EPISODE. Not the user's identity: a sign-out and a sign-in as
  // the SAME subject are two different sessions, and the second must not inherit the
  // first one's bearer. `isAuthenticated` flipping is what separates them; `sub` is
  // carried too so a direct swap between users is also a boundary.
  const sessionKey = `${isAuthenticated}:${user?.sub ?? ''}`
  // The access-token fetch result, held together with the session that fetched it.
  const [session, setSession] = useState<{ key: string; snapshot: AuthSnapshot | null }>({
    key: sessionKey,
    snapshot: null,
  })

  // THE TOKEN EPOCH. A monotonic counter naming the authentication attempt a token
  // request belongs to. Every request captures the epoch it was created under and
  // re-checks it before touching storage or state, so abandoning outstanding work is
  // a single synchronous increment.
  //
  // WHY THE EFFECT-LOCAL `active` FLAG IS NOT ENOUGH. Cleanup only runs when a
  // dependency changes, and logout does not change one: the Auth0 SDK reports
  // isAuthenticated=false some time AFTER logout begins. In that window the old
  // request is still considered live, and a resolve lands writeToken() — putting the
  // credential the user just signed out of back into storage. The epoch closes that
  // window because logout can invalidate synchronously, at the moment of intent,
  // without waiting for the SDK to catch up.
  const tokenEpochRef = useRef(0)

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
    // Nothing to fetch while unauthenticated. No reset here either: the session tag
    // below is what makes the previous episode's result unreadable, so this effect
    // never writes state it did not fetch.
    if (!isAuthenticated) {
      return
    }
    // This request's epoch. Taken before the call so anything that invalidates
    // afterwards — logout, or Auth0 reporting no session — leaves it behind.
    const epoch = ++tokenEpochRef.current
    // Retained as a second, narrower guard for the ordinary dependency-change case.
    let active = true
    // Fetch the access token and write it into the SAME localStorage slot the stub
    // path uses, so client.ts (sessionToken -> readToken) is unchanged. Re-runs when
    // Auth0's auth state changes. Token-refresh-on-401 is a deferred refinement:
    // getAccessTokenSilently would be re-invoked on a 401 from dis-ui-server; that
    // wiring is out of scope for the built-not-wired step.
    getAccessTokenSilently()
      .then((token) => {
        // A stale SUCCESS must not write the bearer, the snapshot, or the status.
        if (!active || epoch !== tokenEpochRef.current) {
          return
        }
        writeToken(token)
        setSession({ key: sessionKey, snapshot: snapshotFromToken(token) })
      })
      .catch(() => {
        // A stale FAILURE is the more dangerous half: its error path CLEARS storage
        // and the snapshot, so an unguarded late rejection from an abandoned request
        // signs the current session out. Same epoch check, same reason.
        if (!active || epoch !== tokenEpochRef.current) {
          return
        }
        clearToken()
        setSession({ key: sessionKey, snapshot: null })
      })
    return () => {
      active = false
    }
  }, [isAuthenticated, getAccessTokenSilently, sessionKey])

  // A SESSION CAN END WITHOUT PASSING THROUGH logout() — an SDK-side expiry, a sign
  // out in another tab. When Auth0 has definitively resolved to no session, abandon
  // any outstanding request and make sure the bearer is not still sitting in storage
  // for client.ts to attach to the next request. Storage only; the snapshot is
  // already handled by the session-boundary reset during render.
  useEffect(() => {
    if (isLoading || isAuthenticated) {
      return
    }
    tokenEpochRef.current += 1
    clearToken()
  }, [isLoading, isAuthenticated])

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

  // CROSSING A SESSION BOUNDARY DISCARDS THE PREVIOUS EPISODE'S RESULT, here in
  // render rather than from an effect. This is React's documented way to reset state
  // when an input changes, and it is what react-hooks/set-state-in-effect steers
  // toward; the reset lands before anything can observe the old value, and no effect
  // writes state it did not fetch.
  //
  // CLEARED AT THE BOUNDARY, NOT COMPARED AT READ TIME. Comparing a stored tag
  // against the current one looks equivalent and is not: sign out and back in as the
  // SAME subject returns the key to a value it already had, so a comparison would
  // hand the new session the old session's snapshot. Clearing as the boundary is
  // crossed has no such hole — there is nothing left to match.
  let snapshot = session.snapshot
  if (session.key !== sessionKey) {
    setSession({ key: sessionKey, snapshot: null })
    snapshot = null
  }
  // THE CURRENT SESSION'S bearer is in storage. writeToken() happens immediately
  // before the tagged write above and only on the resolve path, so a readable
  // snapshot and a usable bearer are the same fact; a pending or failed fetch, or a
  // result belonging to a finished session, all read as not-ready.
  const tokenReady = snapshot !== null

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

  // The signed-in person, for DISPLAY only. `user` is the Auth0 SDK's decoded ID TOKEN
  // (distinct from the access token decoded above for authz claims), populated because
  // App.tsx requests `openid profile email`. Nothing here gates anything.
  //
  // EXPECT `name` TO BE ABSENT. The shared cortex-cm-claims Action stamps no name claim,
  // so displayNameFor falls back to deriving from the email — the same derivation
  // cm-frontend uses, mirrored deliberately so one person reads the same in both products.
  // Also read the namespaced email claim as a fallback: that is the one the Action
  // guarantees, whereas standard `email` depends on the profile scope surviving.
  const profile = useMemo<UserProfile | null>(() => {
    if (!user) return null
    const namespacedEmail = user[`${NS}/email`]
    const email =
      typeof user.email === 'string' && user.email.length > 0
        ? user.email
        : typeof namespacedEmail === 'string' && namespacedEmail.length > 0
          ? namespacedEmail
          : null
    const name = typeof user.name === 'string' && user.name.length > 0 ? user.name : null
    if (name === null && email === null) return null
    return { name, email }
  }, [user])

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      snapshot,
      profile,
      // Customer Master (CM) is the single login entry point. This branch is only
      // reached with NO DIS session (an existing SSO session makes isAuthenticated
      // true, so the silent-token path above handles it without ever calling login).
      // Instead of DIS running its own interactive Auth0 login, redirect to CM's
      // login (which lands on My Cortex). The rawToken arg is ignored in real mode.
      async login() {
        window.location.href = import.meta.env.VITE_CM_LOGIN_URL ?? window.location.origin
      },
      logout() {
        // ORDER IS THE WHOLE POINT. Invalidate FIRST, synchronously, so every
        // request created before this moment is already dead before anything else
        // happens — including the ones that will resolve during the gap before the
        // SDK reports isAuthenticated=false. Clearing storage first and invalidating
        // afterwards leaves exactly the window where a late resolve restores the
        // credential the user just discarded.
        tokenEpochRef.current += 1
        clearToken()
        // Drop the snapshot now rather than waiting for the SDK: logout is the
        // intent, and until Auth0 catches up the boundary reset has nothing to fire
        // on. Functional form so this does not capture sessionKey.
        setSession((previous) => ({ key: previous.key, snapshot: null }))
        void logout({ logoutParams: { returnTo: window.location.origin } })
      },
    }),
    [status, snapshot, profile, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
