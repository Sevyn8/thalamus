import { createContext } from 'react'

import type { AuthSnapshot } from './AuthSnapshot'

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated'

// Who the signed-in person IS, for display only. Deliberately NOT on AuthSnapshot:
// that type is defined as "derived purely by decoding the auth token's claims", and
// these fields are not access-token claims. In real mode they come from the ID token
// via the Auth0 SDK's `user`; in fixture mode from the chosen dev persona. Either way
// they are presentation, never authorization — nothing gates on them.
//
// BOTH FIELDS ARE NULLABLE and `name` is the one that usually is. The shared
// cortex-cm-claims Auth0 Action stamps user_id / user_type / tenant_id / email and NO
// name claim, because Customer Master creates users via the Management API with an
// email and app_metadata only. So consumers should expect to render the email-derived
// fallback (see auth/displayName.ts) rather than a real name.
export type UserProfile = {
  name: string | null
  email: string | null
}

export type AuthContextValue = {
  status: AuthStatus
  snapshot: AuthSnapshot | null
  // Display identity for the signed-in user. null while loading/unauthenticated, and
  // null is a legitimate steady state — a consumer renders nothing rather than a
  // placeholder.
  profile: UserProfile | null
  // Verifies and stores a raw token, then marks the user authenticated. Rejects
  // (and changes nothing) if the token is invalid.
  login: (rawToken: string) => Promise<void>
  logout: () => void
}

// Kept in its own module (no component export) so the provider and hook files
// each export a single concern and stay clean under react-refresh lint rules.
export const AuthContext = createContext<AuthContextValue | null>(null)
