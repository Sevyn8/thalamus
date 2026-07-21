import { NextResponse } from "next/server";

import { auth0 } from "@/lib/auth0";

// Bridges the server-held Auth0 access token to the client-side BFF attach
// seam (lib/api/client.ts). getAuthToken()'s cache is warmed by fetching this
// route (with the session cookie), so client.ts stays source-blind: it reads a
// token, it does not care that the source is now the Auth0 session rather than
// a pre-minted dev JWT. The token carries aud=https://api.sevyn8.com so
// cm-backend accepts it. Returns { token: null } when there is no session.
//
// force-dynamic keeps the session read at request time (never prerendered).
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const { token } = await auth0.getAccessToken();
    return NextResponse.json({ token });
  } catch {
    // No session / not authenticated: the middleware normally redirects
    // before this is reached; return null so the client omits the header
    // and the backend 401s, which the UI surfaces normally.
    return NextResponse.json({ token: null });
  }
}
