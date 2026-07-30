import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import type { AuthSnapshot } from './AuthSnapshot'
import { AuthContext } from './context'
import type { AuthContextValue, AuthStatus, UserProfile } from './context'
import { PERSONAS } from './dev/personas'
import { clearToken, readToken, writeToken } from './storage'
import { verifyToken } from './verifyToken'

export function AuthProvider({ children }: { children: ReactNode }) {
  // Resolve the no-token case synchronously at init so the effect only ever runs
  // the async verification path (no synchronous setState in the effect body).
  const [status, setStatus] = useState<AuthStatus>(() =>
    readToken() === null ? 'unauthenticated' : 'loading',
  )
  const [snapshot, setSnapshot] = useState<AuthSnapshot | null>(null)

  // On mount, restore a stored token if present. An invalid, expired, or
  // malformed token is cleared and the user is left unauthenticated; AuthBoundary
  // then redirects.
  useEffect(() => {
    const raw = readToken()
    if (raw === null) {
      return
    }
    let active = true
    verifyToken(raw)
      .then((restored) => {
        if (!active) {
          return
        }
        setSnapshot(restored)
        setStatus('authenticated')
      })
      .catch(() => {
        if (!active) {
          return
        }
        clearToken()
        setSnapshot(null)
        setStatus('unauthenticated')
      })
    return () => {
      active = false
    }
  }, [])

  // FIXTURE-MODE display identity. The stub token carries NO profile claims by design
  // (signStubToken mints only the CM claim set), so the name/email are recovered from the
  // chosen dev persona instead — matched on `sub`, which signStubToken sets as the token
  // subject and toSnapshot maps to userId. That needs no extra persistence: the token
  // already carries the only key required.
  //
  // Real mode derives its display name from the email because no name claim exists there;
  // fixture personas carry a hand-written `name` ("A. Kowalski"), so fixture mode will look
  // slightly better than production for the same person. That gap is the fixtures being
  // prettier than reality, not a bug.
  const profile = useMemo<UserProfile | null>(() => {
    if (snapshot === null) return null
    const persona = PERSONAS.find((candidate) => candidate.sub === snapshot.userId)
    if (persona === undefined) return null
    return { name: persona.name, email: persona.email }
  }, [snapshot])

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      snapshot,
      profile,
      async login(rawToken: string) {
        const next = await verifyToken(rawToken)
        writeToken(rawToken)
        setSnapshot(next)
        setStatus('authenticated')
      },
      logout() {
        clearToken()
        setSnapshot(null)
        setStatus('unauthenticated')
      },
    }),
    [status, snapshot, profile],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
