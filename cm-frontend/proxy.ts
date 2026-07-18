import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// ============================================================================
// Auth proxy / middleware. Runs on every request (per the matcher below)
// before Next.js's file-system routing.
//
// Phase 5a.3 audit (post-Phase 4 wiring; pre-DIS routes):
//
//   - PUBLIC_PREFIXES — paths that bypass auth entirely. /dev (persona
//     switcher + dev mint shims), /login (Auth0 surface, future), /mfa,
//     /forgot-password, /accept-invite (auth-flow surfaces). The root "/"
//     is also public — it just redirects to a dashboard or login depending
//     on cookie state via app/page.tsx.
//
//   - PROTECTED_PREFIXES — paths that require a persona cookie. Two
//     categories:
//       (a) Product namespaces: /superadmin (Ithina) and /dis (DIS — added
//           in Phase 5a.3 ahead of Phase 5b.1's actual routes; protecting
//           early means an unauth user clicking DIS in the product
//           switcher lands on /dev/login?from=/dis/... rather than a raw
//           404 they have no context for).
//       (b) Product-agnostic auth-required surfaces: /profile,
//           /notifications, /approvals — top-level pages outside both
//           product trees but still require auth.
//
//   - Note on /ithina/*: there are no /ithina routes in the app tree.
//     next.config.ts redirects /ithina/:path* → /superadmin/:path* as a
//     future-proofing hedge. Both Next.js redirects (config-level) and
//     middleware (proxy.ts) run on every request — see the smoke notes in
//     the Phase 5a.3 commit for the observed redirect-chain ordering.
// ============================================================================

// Non-secret marker cookie set by setCurrentPersona() in
// lib/auth/getAuthToken.ts. Value is just the persona id (e.g. "anjali");
// the JWT itself never touches the cookie. Middleware uses cookie
// presence to decide redirect-to-login, NOT for any authn/authz check.
const PERSONA_COOKIE = "__ithina_dev_persona";

const PUBLIC_PREFIXES = [
  "/dev",
  "/login",
  "/forgot-password",
  "/accept-invite",
  "/mfa",
] as const;

// Protected namespaces. Order doesn't matter (any-match logic). Adding a
// new product namespace here is the load-bearing step that gates the
// product behind auth — must happen *before* the routes light up, not
// after, to avoid a window where unauth requests leak to 404s without
// the redirect-to-login UX.
const PROTECTED_PREFIXES = [
  "/superadmin",  // Ithina
  "/dis",         // DIS (Phase 5b.1+ adds the actual routes; protection in place from 5a.3)
  "/my-ithina",   // Phase 5d.1: launcher route
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

export function proxy(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;

  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  if (!isProtectedPath(pathname)) {
    // Anything unmatched (e.g., asset-shaped paths the matcher didn't
    // exclude, internal Next.js routes) passes through without auth.
    // Anything we want to protect must be in PROTECTED_PREFIXES.
    return NextResponse.next();
  }

  // Runtime, non-prefixed env. Middleware runs server-side per request,
  // so this is read at runtime rather than inlined at build.
  const authMode = process.env.AUTH_MODE === "auth0" ? "auth0" : "stub";

  if (authMode === "stub") {
    const hasPersona = !!request.cookies.get(PERSONA_COOKIE)?.value;
    if (!hasPersona) {
      const url = request.nextUrl.clone();
      url.pathname = "/dev/login";
      url.searchParams.set("from", pathname);
      return NextResponse.redirect(url);
    }
    return NextResponse.next();
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|jpeg|gif|svg|ico|webp)$).*)"],
};
