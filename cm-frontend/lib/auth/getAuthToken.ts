// The BFF token seam. getAuthToken() is a synchronous read of a module-level
// cache that prefetchAuthToken() warms; lib/api/client.ts attaches whatever it
// returns as the Bearer, source-blind. The token SOURCE is the Auth0 session:
// prefetch fetches /api/access-token (a server route that reads the session and
// returns the cm-backend-valid access token). No personas, no dev JWTs.

// A single-slot cache: `undefined` means "not fetched yet"; `string` is the
// session access token; `null` means "resolved, no token" (no session).
let token: string | null | undefined = undefined;
let inFlight: Promise<void> | null = null;

// Fetch + cache the session access token exactly once. getAuthToken() stays
// synchronous by reading the cache; AuthBoundary triggers the prefetch and
// waits on resolution (see isAuthTokenResolved). Concurrent callers share one
// request. credentials: "include" so the session cookie reaches /api/access-token.
export function prefetchAuthToken(): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  if (token !== undefined) return Promise.resolve();
  if (inFlight) return inFlight;

  const request = (async () => {
    let resolved: string | null = null;
    try {
      const res = await fetch("/api/access-token", { credentials: "include" });
      if (res.ok) {
        const body = (await res.json()) as { token?: string | null };
        resolved = typeof body.token === "string" && body.token ? body.token : null;
      }
    } catch {
      // Network failure resolves to null; apiFetch omits the header and the
      // backend returns 401, which the UI surfaces normally.
    } finally {
      token = resolved;
      inFlight = null;
      notifyAuthChange();
    }
  })();

  inFlight = request;
  // Signal the loading transition so subscribers re-render and gate.
  notifyAuthChange();
  return request;
}

// True once the token request has settled (to a token or to null).
export function isAuthTokenResolved(): boolean {
  if (typeof window === "undefined") return false;
  return token !== undefined;
}

// Reactive key for useSyncExternalStore consumers. Changes when the token
// finishes resolving so a subscriber re-renders and clears any loading gate.
export function getAuthStateKey(): string {
  if (typeof window === "undefined") return "ssr";
  const resolved = token !== undefined;
  const present = resolved && !!token;
  return `${resolved ? "1" : "0"}:${present ? "1" : "0"}`;
}

// Synchronous read of the cached session access token. Returns null when not
// yet fetched or when there is no session. apiFetch tolerates null by omitting
// the Authorization header; the backend then returns 401.
export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return token ?? null;
}

// Async accessor that GUARANTEES the token has been fetched before it resolves,
// mirroring ensureRuntimeConfig() in lib/api/client.ts. apiFetch awaits this so an
// authenticated request never fires during the early-load window (before the store
// is warmed) with a missing Authorization header -> spurious 401 / auto-logout.
//
// - Already cached (truthy) -> return it immediately.
// - Otherwise delegate to prefetchAuthToken(), which fetches /api/access-token
//   exactly once and dedupes concurrent callers via the shared in-flight promise
//   (the token-fetch logic is NOT duplicated here). Then read the resolved cache.
// - No session (endpoint empty/401) resolves the cache to null; we return null
//   WITHOUT throwing, so unauthenticated contexts (login page) are unaffected.
export async function ensureAuthToken(): Promise<string | null> {
  const cached = getAuthToken();
  if (cached) return cached;
  await prefetchAuthToken();
  return getAuthToken();
}

// Clear the cached token (used on logout so a stale token is not attached).
export function clearAuthToken(): void {
  token = undefined;
  inFlight = null;
  notifyAuthChange();
}

// Tiny pub-sub so React components can subscribe to token changes via
// useSyncExternalStore without each setting up its own listener.
type Listener = () => void;
const listeners = new Set<Listener>();

function notifyAuthChange(): void {
  for (const fn of listeners) fn();
}

export function subscribeAuthChange(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
