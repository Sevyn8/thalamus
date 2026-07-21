import { Auth0Client } from "@auth0/nextjs-auth0/server";

// The single Auth0 SDK client (nextjs-auth0 v4, confidential server-side
// session). Domain / clientId / clientSecret / secret / appBaseUrl are read
// from env by the SDK (AUTH0_DOMAIN, AUTH0_CLIENT_ID, AUTH0_CLIENT_SECRET,
// AUTH0_SECRET, APP_BASE_URL). The audience is MANDATORY: without it Auth0
// returns only an ID token, and getAccessToken would not yield a token the
// cm-backend (which validates aud=https://api.sevyn8.com) accepts. Namespace
// for the custom identity claims is https://sevyn8.com/ (stamped by the shared
// cortex-cm-claims Action); the frontend reads them off the session user.
export const auth0 = new Auth0Client({
  authorizationParameters: {
    audience: process.env.AUTH0_AUDIENCE ?? "https://api.sevyn8.com",
    scope: "openid profile email",
  },
});
