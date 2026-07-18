// Single auth indirection point. The future Auth0 swap replaces the body
// of getAuthToken() with auth0Client.getAccessTokenSilently() (or whatever
// the SDK exposes); the export signature stays the same and nothing else
// in the codebase needs to change.

import { isPersonaId, type PersonaId } from "./personas";

const PERSONA_STORAGE_KEY = "ithina:dev-persona";
const PERSONA_COOKIE = "__ithina_dev_persona";
// Match Sanjeev's handoff: dev JWTs are 7-day. Refresh cookie on every set
// so it tracks the freshest mint, not the first one.
const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7;

// Module-level cache of dev tokens fetched from /api/dev-token. The token
// lives in non-prefixed server env (DEV_JWT_MAP) and is dispensed at
// runtime, so it is no longer inlined into the bundle at build time. A
// cache entry of null means "resolved, no token for this persona" (e.g.
// Kira); the absence of an entry means "not yet fetched".
const tokenCache = new Map<PersonaId, string | null>();
const inFlight = new Map<PersonaId, Promise<void>>();

// Fetch + cache the dev token for a persona exactly once. getAuthToken()
// stays synchronous by reading this cache; AuthBoundary triggers the
// prefetch and waits on resolution (see isAuthTokenResolved). Concurrent
// callers for the same persona share one request.
export function prefetchAuthToken(persona: PersonaId): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  if (tokenCache.has(persona)) return Promise.resolve();
  const existing = inFlight.get(persona);
  if (existing) return existing;

  const request = (async () => {
    let resolved: string | null = null;
    try {
      const res = await fetch(
        `/api/dev-token?persona=${encodeURIComponent(persona)}`,
        { credentials: "omit" },
      );
      if (res.ok) {
        const body = (await res.json()) as { token?: string | null };
        resolved = typeof body.token === "string" && body.token ? body.token : null;
      }
    } catch {
      // Network failure resolves to null; apiFetch omits the header and
      // the backend returns 401, which the UI surfaces normally.
    } finally {
      tokenCache.set(persona, resolved);
      inFlight.delete(persona);
      notifyAuthChange();
    }
  })();

  inFlight.set(persona, request);
  // Signal the loading transition so subscribers re-render and gate.
  notifyAuthChange();
  return request;
}

// True once the active persona's token request has settled (to a token
// or to null). AuthBoundary uses this to decide between "still loading"
// and "no valid session, redirect".
export function isAuthTokenResolved(): boolean {
  if (typeof window === "undefined") return false;
  return tokenCache.has(getCurrentPersona());
}

// Reactive key for useSyncExternalStore consumers. Its value changes when
// the active persona switches or when its token finishes resolving, so a
// subscriber re-renders and clears any loading gate.
export function getAuthStateKey(): string {
  if (typeof window === "undefined") return "ssr";
  const persona = getCurrentPersona();
  const resolved = tokenCache.has(persona);
  const present = resolved && !!tokenCache.get(persona);
  return `${persona}:${resolved ? "1" : "0"}:${present ? "1" : "0"}`;
}

// SSR fallback returns 'anjali'. Server-rendered HTML is overwritten on
// client hydration once localStorage is read; AuthBoundary gates child
// render on a client-side ready flag to avoid hydration mismatch on
// persona-displaying UI.
export function getCurrentPersona(): PersonaId {
  if (typeof window === "undefined") return "anjali";
  const stored = window.localStorage.getItem(PERSONA_STORAGE_KEY);
  return isPersonaId(stored) ? stored : "anjali";
}

export function setCurrentPersona(persona: PersonaId): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(PERSONA_STORAGE_KEY, persona);
  // Marker cookie so the proxy middleware can gate protected routes
  // server-side. Value is non-secret (just the persona id); the JWT
  // never touches the cookie.
  document.cookie = `${PERSONA_COOKIE}=${persona}; path=/; max-age=${COOKIE_MAX_AGE_SECONDS}; SameSite=Lax`;
  notifyAuthChange();
  // Warm the token cache for the picked persona so getAuthToken() has a
  // value ready by the time the authenticated surface mounts.
  void prefetchAuthToken(persona);
}

export function clearCurrentPersona(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(PERSONA_STORAGE_KEY);
  document.cookie = `${PERSONA_COOKIE}=; path=/; max-age=0; SameSite=Lax`;
  notifyAuthChange();
}

export function hasPersonaSet(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(PERSONA_STORAGE_KEY) !== null;
}

// Synchronous read of the active persona's cached dev token. Returns null
// when the token has not been fetched yet, or when no token is configured
// for the persona (e.g. Kira, or before DEV_JWT_MAP is populated).
// apiFetch tolerates null by omitting the Authorization header; the
// backend then returns 401, which the UI surfaces normally. The cache is
// warmed by prefetchAuthToken() on persona set and on initial load.
export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return tokenCache.get(getCurrentPersona()) ?? null;
}

// Tiny pub-sub so React components can subscribe to persona changes via
// useSyncExternalStore without each component setting up its own storage
// listener.
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
