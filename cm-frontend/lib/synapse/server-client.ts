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
// WHAT THAT MEANS FOR AUTHORISATION, stated because it is easy to get wrong: the
// ID token proves WHICH WORKLOAD is calling, not WHICH PERSON. The person is
// authorised separately — the page is under /superadmin, the middleware requires
// a session, and the sidebar entry requires a GLOBAL tuple. The BFF additionally
// refuses anything that is not PLATFORM.
//
// It follows that the BFF cannot see the human's identity at all on this path,
// which is a real limitation and is why every 8a route is PLATFORM-wide rather
// than per-user. A route needing the acting user would have to forward the Auth0
// token as well; none does.
//
// ============================================================================
// THE AUDIT GAP THIS CREATES, AND WHEN IT STOPS BEING ACCEPTABLE
// ============================================================================
// Because the BFF is authenticated by the FRONTEND's service account, it cannot
// see which superadmin is looking. It knows PLATFORM; it does not know a person.
//
// So NO SYNAPSE READ IS ATTRIBUTABLE TO A HUMAN. Customer Master's audit log
// covers CM's own actions and never sees these requests at all — a superadmin
// reading every tenant's provisioning, runs and action counts leaves no trace
// anywhere.
//
// THAT IS FINE FOR SLICE 8a, and the reason is narrow rather than comfortable:
// every route is read-only, so the worst an unattributable request can do is
// look. It is not fine for anything that changes state — an unattributable
// INSERT into synapse.provision is a change to a customer's configuration with
// nobody's name on it, and enabled_at is an attribution denominator.
//
// THE TRIGGER IS: THE FIRST SYNAPSE ROUTE THAT WRITES, which is 8b. At that
// point the acting user has to reach the BFF — forwarding the caller's Auth0
// token alongside the ID token, so the service account proves WHICH WORKLOAD and
// the Auth0 token proves WHICH PERSON — and the write has to be recorded
// somewhere an auditor can find it.
//
// LOCALLY there is no metadata server, so SYNAPSE_BFF_TOKEN (a token minted by
// hand) is used if present. Absent both, the call fails loudly rather than going
// out unauthenticated.

import "server-only";

const BASE = process.env.SYNAPSE_BFF_URL ?? "";

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

// Every read is a GET and there is no post/put/delete helper here, deliberately:
// slice 8a holds no write path, and the BFF has no writer credential to serve one
// with. Adding a mutation means adding it in both places, visibly.
export async function synapseGet<T>(path: string): Promise<T> {
  if (!BASE) {
    throw new SynapseUnavailable(
      "SYNAPSE_BFF_URL is not configured; the Synapse console cannot load",
    );
  }
  const token = await identityToken(BASE);
  const response = await fetch(`${BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
    // A console reads live state. Caching a fleet view would show an operator a
    // stale "needs you" panel, which is the one panel whose whole value is being
    // current.
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SynapseUnavailable(
      `Synapse BFF ${path} returned ${response.status}`,
    );
  }
  return (await response.json()) as T;
}
