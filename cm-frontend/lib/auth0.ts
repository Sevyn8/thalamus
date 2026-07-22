import { Auth0Client } from "@auth0/nextjs-auth0/server";
import { decodeJwt } from "jose";

// The single Auth0 SDK client (nextjs-auth0 v4, confidential server-side
// session). Domain / clientId / clientSecret / secret / appBaseUrl are read
// from env by the SDK (AUTH0_DOMAIN, AUTH0_CLIENT_ID, AUTH0_CLIENT_SECRET,
// AUTH0_SECRET, APP_BASE_URL). The audience is MANDATORY: without it Auth0
// returns only an ID token, and getAccessToken would not yield a token the
// cm-backend (which validates aud=https://api.sevyn8.com) accepts. Namespace
// for the custom identity claims is https://sevyn8.com/ (stamped by the shared
// cortex-cm-claims Action); the frontend reads them off the session user.

// The namespaced identity claims the Action stamps on the ID token. v4 strips
// non-standard claims from session.user by default (filterDefaultIdTokenClaims);
// providing beforeSessionSaved replaces that filter, so we merge these four back
// onto the session user. /auth/profile returns session.user, so this is what
// claimsFromSessionUser then reads.
const NS = "https://sevyn8.com/";
const CUSTOM_CLAIMS = [
  `${NS}tenant_id`,
  `${NS}user_type`,
  `${NS}user_id`,
  `${NS}email`,
] as const;

export const auth0 = new Auth0Client({
  authorizationParameters: {
    audience: process.env.AUTH0_AUDIENCE ?? "https://api.sevyn8.com",
    scope: "openid profile email",
  },
  // Merge the namespaced identity claims from the ID token into session.user so
  // they survive persistence (and /auth/profile surfaces them). The second arg
  // is the raw ID-token string; decode it (the SDK has already validated it) to
  // read the custom claims.
  async beforeSessionSaved(session, idToken) {
    if (!idToken) return session;
    const claims = decodeJwt(idToken);
    const extra: Record<string, unknown> = {};
    for (const key of CUSTOM_CLAIMS) {
      if (claims[key] !== undefined) extra[key] = claims[key];
    }
    return { ...session, user: { ...session.user, ...extra } };
  },
});
