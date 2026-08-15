import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { auth0 } from "@/lib/auth0";

// ============================================================================
// Auth middleware (Next 16 renamed middleware -> proxy). Runs on every request
// per the matcher below, before file-system routing.
//
// Real Auth0 is the ONLY auth path (the dev stub is retired). Flow:
//   1. auth0.middleware(request) mounts the SDK routes (/auth/login,
//      /auth/logout, /auth/callback, /auth/profile, /auth/access-token) and
//      refreshes the session cookie. Its response is returned as-is for /auth/*.
//   2. Public paths pass through.
//   3. Protected prefixes require a session; unauthenticated requests are
//      redirected to /auth/login.
//
//   - Note on /ithina/*: there are no /ithina routes in the app tree.
//     next.config.ts redirects /ithina/:path* -> /superadmin/:path*.
// ============================================================================

const PUBLIC_PREFIXES = [
  "/auth", // Auth0 SDK routes (login/logout/callback/profile/access-token)
  "/forgot-password",
  "/mfa",
] as const;

// Protected namespaces. Adding a new product namespace here is the load-bearing
// step that gates it behind auth; the middleware matcher (below) must also cover
// it, which it does (it excludes only static assets).
const PROTECTED_PREFIXES = [
  "/superadmin", // Ithina
  "/dis", // DIS
  "/my-sevyn8", // launcher route
  "/profile",
  "/notifications",
  "/approvals",
] as const;

function isPublicPath(pathname: string): boolean {
  if (pathname === "/") return true;
  return PUBLIC_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export async function middleware(request: NextRequest): Promise<NextResponse> {
  // Always let the SDK mount /auth/* and refresh the session first.
  const authResponse = await auth0.middleware(request);

  const { pathname } = request.nextUrl;

  // /auth/* is handled entirely by the SDK response above.
  if (pathname.startsWith("/auth/")) {
    return authResponse;
  }

  if (isPublicPath(pathname) || !isProtectedPath(pathname)) {
    return authResponse;
  }

  // Protected path: require a session, else send to Auth0 login.
  const session = await auth0.getSession(request);
  if (!session) {
    const url = request.nextUrl.clone();
    url.pathname = "/auth/login";
    url.searchParams.set("returnTo", pathname);
    return NextResponse.redirect(url);
  }

  return authResponse;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|jpeg|gif|svg|ico|webp)$).*)"],
};
