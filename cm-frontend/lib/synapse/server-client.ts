// Server-side client for the Synapse BFF. NEVER imported by a client component.
//
// ============================================================================
// THE BROWSER NEVER TALKS TO THIS SERVICE, AND THAT IS THE POINT
// ============================================================================
// Everything else in this app fetches from cm-backend IN THE BROWSER, with the
// user's Auth0 access token (lib/api/client.ts). That is why cm-backend carries
// an `allUsers` invoker binding: it has to be reachable from a browser.
//
// Synapse does not. These calls happen in Next.js SERVER components, so:
//
//   - the Synapse BFF needs no public invoker binding — IAM only
//   - no Synapse response or token ever reaches the browser
//   - there is no CORS surface to configure or get wrong
//
// A new service is the cheapest possible moment not to inherit the standing HIGH
// finding that every HTTP service here is anonymously reachable. Synapse is the
// first one that does not, which makes it a working precedent rather than a
// theory about the other four.
//
// ============================================================================
// HOW THE CALL IS AUTHENTICATED
// ============================================================================
// Cloud Run's metadata server mints a Google-signed ID token for a target
// audience. Cloud Run validates it against the service's IAM policy before the
// request reaches the container. So the caller identity is the FRONTEND's
// service account, not the human's Auth0 token.
//
// ============================================================================
// TWO TOKENS, TWO LAYERS, EACH PROVING ITS OWN THING
// ============================================================================
//   Authorization:              the USER's Auth0 access token  -> the BFF verifies
//   X-Serverless-Authorization: a Google ID token              -> Cloud Run's IAM verifies
//
// Cloud Run checks the second before the request reaches the container; the BFF
// checks the first. IAM PROVES THE WORKLOAD, AUTH0 PROVES THE PERSON. Either
// alone is weaker: IAM alone cannot tell one superadmin from another, and Auth0
// alone would need the service publicly reachable.
//
// X-Serverless-Authorization exists precisely so the two do not collide. If the
// Google token were sent as `Authorization` — as this file did until it was traced
// end to end — Cloud Run would let the request in and the BFF would then try to
// verify a Google-signed token against AUTH0's JWKS, failing every request with a
// 401. Both halves were correct in isolation; one slice wrote both sides of the
// wire and nobody held them up against each other.
//
// WHY THE AUTH0 SIDE ALREADY FITS, verified rather than assumed. lib/auth0.ts
// requests `audience: https://api.sevyn8.com`, so Auth0 issues a JWT access token
// rather than an opaque one, with exactly the audience SYNAPSE_JWT_AUDIENCE
// expects. And cm-backend's production verifier
// (admin_backend/auth/auth0.py) validates that same access token and REQUIRES
// `https://sevyn8.com/user_type` on it, rejecting the request otherwise — a live
// service that would be failing every call if the claim were absent. So the BFF's
// require_platform works on the token below unchanged.
//
// ============================================================================
// THE AUDIT POSITION, ONCE THE FIX LANDS
// ============================================================================
// With the user's Auth0 token verified here, the BFF DOES see the person:
// Identity.subject is the Auth0 `sub`. So the correct statement is narrower than
// "no Synapse read is attributable" — which described a design that does not
// function:
//
//   THE IDENTITY IS AVAILABLE AND NOTHING RECORDS IT.
//
// Every read resolves a real person and writes that fact nowhere. Customer
// Master's audit log covers CM's own actions and never sees these requests, so a
// superadmin reading every tenant's provisioning, runs and action counts leaves
// no trace — not because the identity is unknown, but because nothing persists it.
//
// Fine for slice 8a for a narrow reason rather than a comfortable one: every
// route is read-only, so the worst an unattributable request can do is look. Not
// fine for a write — an unattributable INSERT into synapse.provision changes a
// customer's configuration with nobody's name on it, and enabled_at is a
// denominator.
//
// THE TRIGGER IS UNCHANGED: THE FIRST SYNAPSE ROUTE THAT WRITES, which is 8b. The
// work is then to RECORD the identity that is already in hand, not to obtain one.
//
// LOCALLY there is no metadata server, so SYNAPSE_BFF_TOKEN (a token minted by
// hand) is used if present. Absent both, the call fails loudly rather than going
// out unauthenticated.

import "server-only";

import { auth0 } from "@/lib/auth0";

// NO MODULE-SCOPE ENV READ HERE, deliberately. `const BASE = process.env.SYNAPSE_BFF_URL`
// lived on this line and was bound at import — which froze it at container start and,
// worse, at BUILD time for any page Next.js prerendered. See synapseGet below.

const METADATA_URL =
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity";

async function identityToken(audience: string): Promise<string> {
  const override = process.env.SYNAPSE_BFF_TOKEN;
  if (override) return override;

  const response = await fetch(`${METADATA_URL}?audience=${encodeURIComponent(audience)}`, {
    headers: { "Metadata-Flavor": "Google" },
    cache: "no-store",
  });
  if (!response.ok) {
    // Loud, and it names both ways out. A silent fall-through to an
    // unauthenticated request would be answered with 403 by Cloud Run and read
    // as "the BFF is down".
    throw new Error(
      `could not mint an identity token for ${audience} (metadata server said ` +
        `${response.status}). On Cloud Run this means the runtime service account ` +
        `cannot issue tokens; locally, set SYNAPSE_BFF_TOKEN.`,
    );
  }
  return (await response.text()).trim();
}

export class SynapseUnavailable extends Error {}

// The acting user's Auth0 access token, read from the server-side session.
//
// getAccessToken() THROWS when there is no session (the SDK's
// AccessTokenErrorCode.MISSING_SESSION), which is the same path
// /api/access-token catches to return { token: null }. Reaching here without one
// should be impossible — middleware.ts redirects unauthenticated requests to
// /auth/login before any /superadmin page renders — so it is translated into a
// named failure rather than allowed to surface as a raw SDK error or, worse, an
// Authorization header reading "Bearer undefined" that the BFF would reject as a
// malformed token.
async function userAccessToken(): Promise<string> {
  try {
    const { token } = await auth0.getAccessToken();
    if (!token) throw new Error("session carried no access token");
    return token;
  } catch (cause) {
    throw new SynapseUnavailable(
      `no Auth0 access token for this request (${String(cause)}). The Synapse console is ` +
        `server-rendered and needs the acting user's session; middleware should have ` +
        `redirected an unauthenticated request before reaching this page.`,
    );
  }
}

// Every read is a GET and there is no post/put/delete helper here, deliberately:
// slice 8a holds no write path, and the BFF has no writer credential to serve one
// with. Adding a mutation means adding it in both places, visibly.
export async function synapseGet<T>(path: string): Promise<T> {
  // ==========================================================================
  // THE SESSION READ COMES FIRST, AND THE ORDER IS LOAD-BEARING.
  // ==========================================================================
  // Reading the Auth0 session touches cookies, and touching cookies is what marks
  // this route DYNAMIC to Next.js. The pages also declare `force-dynamic`, but
  // that is a directive an edit can delete; doing the session read first makes the
  // route dynamic BY USE, so both would have to be undone to reintroduce the bug.
  //
  // WHAT HAPPENED WHEN THE CONFIG CHECK RAN FIRST: the throw fired before any
  // cookie was touched, Next.js saw no dynamic API, prerendered the page AT BUILD
  // TIME where SYNAPSE_BFF_URL does not exist, and baked "The Synapse service is
  // not reachable" into static HTML. The container then served a file — no env
  // read, no fetch — while the running revision had the variable set correctly and
  // the BFF's logs stayed empty.
  const userToken = await userAccessToken();

  // READ PER REQUEST, never at module scope. This is runtime config: it can change
  // with a revision bounce and must not need a rebuild. app/api/config/route.ts
  // states the same rule for API_BASE_URL, and said so before this was written.
  const base = process.env.SYNAPSE_BFF_URL ?? "";
  if (!base) {
    // KEPT, because it is right for a genuine runtime outage — BFF down, IAM
    // revoked, VPC broken — and removing it would render a blank page for a real
    // one. What was wrong was that it could be reached at BUILD time.
    throw new SynapseUnavailable(
      "SYNAPSE_BFF_URL is not configured; the Synapse console cannot load",
    );
  }

  const idToken = await identityToken(base);

  const response = await fetch(`${base}${path}`, {
    headers: {
      // Verified by the BFF: proves WHICH PERSON.
      Authorization: `Bearer ${userToken}`,
      // Consumed by Cloud Run IAM before the container sees the request: proves
      // WHICH WORKLOAD. Cloud Run reads this in preference to Authorization, which
      // is why the two can coexist.
      "X-Serverless-Authorization": `Bearer ${idToken}`,
    },
    // A console reads live state. Caching a fleet view would show an operator a
    // stale "needs you" panel, which is the one panel whose whole value is being
    // current.
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SynapseUnavailable(`Synapse BFF ${path} returned ${response.status}`);
  }
  return (await response.json()) as T;
}
