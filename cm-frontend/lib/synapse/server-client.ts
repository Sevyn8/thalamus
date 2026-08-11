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
// ============================================================================
// THE TRIGGER HAS FIRED, TWICE, AND THIS PARAGRAPH SAID IT HAD NOT
// ============================================================================
// It read "THE TRIGGER IS UNCHANGED: THE FIRST SYNAPSE ROUTE THAT WRITES, which
// is 8b." That was already false when 5d shipped the alert-decision POST, and it
// stayed on the page while a second write landed in 5e. A comment naming its own
// falsification condition is worth more than one that is merely correct today,
// and it still goes stale silently, because nothing re-reads it when the
// condition fires. This is the second instance of that exact failure in this
// console; the other is in the ingress paragraph of the BFF's terraform module.
//
// WHERE THE TWO WRITES STAND NOW:
//
//   5d, alert decisions -> synapse.action_events carries actor_subject on every
//        row. The decision and its attribution are the same row, so this one is
//        genuinely closed.
//   5e, provisioning    -> NOT CLOSED. synapse.provision records enabled_at and
//        records NOBODY. The BFF emits a structured log line carrying the Auth0
//        subject, the tenant, the analysis and the timezone, and a log line is
//        not an audit record: Cloud Logging's retention is the ceiling and
//        nothing can answer "who enabled this monitor" from the database at all.
//
// THE REAL HOME is synapse.provision_events, append-only, the same shape as
// synapse.action_events. It is deferred because it IS the append-only enablement
// history in disguise and synapse/schemas/postgres/provision.sql names the first
// DISABLE as that table's trigger, not the first enable. Both get built together
// when a disable arrives.
//
// UNTIL THEN 5e MUST NOT REACH A PRODUCTION TENANT. Same standing condition as
// the provisioning permission being known-broader than the act; see
// synapse_ui_server/cm_permissions.py.
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

// A GET helper and, since slice 5d, exactly one POST helper. The comment here used
// to read "there is no post/put/delete helper, deliberately: slice 8a holds no write
// path" — and it was right that adding a mutation should mean adding it in both
// places, visibly. This is that, done visibly.
//
// THE BROWSER CANNOT DO THIS ITSELF, which is why the write is server-side rather
// than a fetch from a client component. Reaching the BFF needs BOTH tokens below;
// the Google ID token is minted from the runtime service account's metadata, which
// no browser has, and SYNAPSE_BFF_URL is server-only (not NEXT_PUBLIC_).
export async function synapsePost<T>(path: string, body: unknown): Promise<T> {
  // SAME ORDER AS THE GET, and for the same reason: the session read is what marks
  // the caller dynamic. A server action is already dynamic, but the two helpers
  // staying identical in shape is what keeps one from drifting into a bug the other
  // already paid for.
  const userToken = await userAccessToken();
  const base = process.env.SYNAPSE_BFF_URL ?? "";
  if (!base) {
    throw new SynapseUnavailable(
      "SYNAPSE_BFF_URL is not configured; the Synapse console cannot record decisions",
    );
  }
  const idToken = await identityToken(base);

  const response = await fetch(`${base}${path}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${userToken}`,
      "X-Serverless-Authorization": `Bearer ${idToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  if (!response.ok) {
    // 422 carries the BFF's own message naming the legal vocabulary; surfacing the
    // status alone would turn "pick a reason" into "something went wrong".
    const detail = await response.text().catch(() => "");
    throw new SynapseUnavailable(
      `Synapse BFF ${path} returned ${response.status}${detail ? `: ${detail}` : ""}`,
    );
  }
  return (await response.json()) as T;
}

export async function synapseGet<T>(path: string): Promise<T> {
  // READ PER REQUEST, never at module scope. This is runtime config: it can change
  // with a revision bounce and must not need a rebuild. app/api/config/route.ts
  // states the same rule for API_BASE_URL, and said so before this was written.
  //
  // RESOLVED HERE AND CHECKED IN synapseGetFrom, not checked here, and the split is
  // the whole point of the extraction. See that function: the throw for a missing
  // base MUST come after the session read, and putting the check at each call site
  // is how it drifts back in front of it.
  return synapseGetFrom<T>(
    process.env.SYNAPSE_BFF_URL ?? "",
    path,
    "SYNAPSE_BFF_URL is not configured; the Synapse console cannot load",
  );
}

// The same GET, against a base URL the CALLER resolved. Extracted for AXON
// (lib/axon/server-client.ts), which resolves AXON_BFF_URL ?? SYNAPSE_BFF_URL so
// that a future standalone Axon service is one environment variable rather than a
// sweep of call sites.
//
// EXTRACTED RATHER THAN COPIED. A second copy of the two-token dance is a second
// place to send the Google token as `Authorization`, which is the mistake that
// 401'd every Synapse request once and took an end-to-end trace to find.
//
// ==========================================================================
// THE SESSION READ COMES FIRST, AND THE ORDER IS LOAD-BEARING.
// ==========================================================================
// Reading the Auth0 session touches cookies, and touching cookies is what marks
// the route DYNAMIC to Next.js. The pages also declare `force-dynamic`, but that
// is a directive an edit can delete; doing the session read first makes the route
// dynamic BY USE, so both would have to be undone to reintroduce the bug.
//
// WHAT HAPPENED WHEN THE CONFIG CHECK RAN FIRST: the throw fired before any cookie
// was touched, Next.js saw no dynamic API, prerendered the page AT BUILD TIME where
// SYNAPSE_BFF_URL does not exist, and baked "The Synapse service is not reachable"
// into static HTML. The container then served a file, with no env read and no
// fetch, while the running revision had the variable set correctly and the BFF's
// logs stayed empty.
//
// THE MISSING-BASE CHECK THEREFORE LIVES INSIDE THIS FUNCTION, AFTER THE SESSION
// READ, and callers pass a resolved-or-empty string rather than throwing
// themselves. A caller that checked its own env and threw would be that exact bug
// again, in a new file, and lib/axon/server-client.ts is a new file.
export async function synapseGetFrom<T>(
  base: string,
  path: string,
  missingBaseMessage: string,
): Promise<T> {
  const userToken = await userAccessToken();

  if (!base) {
    // KEPT, because it is right for a genuine runtime outage - BFF down, IAM
    // revoked, VPC broken - and removing it would render a blank page for a real
    // one. What was wrong was that it could be reached at BUILD time.
    throw new SynapseUnavailable(missingBaseMessage);
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
