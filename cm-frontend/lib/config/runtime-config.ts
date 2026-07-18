import { useEffect, useSyncExternalStore } from "react";

// Runtime config store. Decouples the API base URL and auth mode from
// build time: the client learns both from /api/config (a force-dynamic
// route that reads non-prefixed server env at request time), so the same
// image can be promoted across projects without a rebuild. Server-side
// callers read process.env directly and skip the HTTP round-trip.

export type RuntimeConfig = {
  apiBaseUrl: string;
  authMode: string;
};

const CONFIG_ENDPOINT = "/api/config";

let config: RuntimeConfig | null = null;
let inFlight: Promise<RuntimeConfig> | null = null;

const listeners = new Set<() => void>();

function notify(): void {
  for (const fn of listeners) fn();
}

function readServerConfig(): RuntimeConfig {
  return {
    apiBaseUrl: process.env.API_BASE_URL ?? "",
    authMode: process.env.AUTH_MODE ?? "stub",
  };
}

// Fetch + cache the runtime config exactly once. Concurrent callers share
// the same in-flight promise. On the server the value comes straight from
// process.env (no /api/config round-trip). Safe to await repeatedly.
export async function ensureRuntimeConfig(): Promise<RuntimeConfig> {
  if (config) return config;

  if (typeof window === "undefined") {
    config = readServerConfig();
    return config;
  }

  if (inFlight) return inFlight;

  inFlight = (async () => {
    let next: RuntimeConfig = { apiBaseUrl: "", authMode: "stub" };
    try {
      const res = await fetch(CONFIG_ENDPOINT, { credentials: "omit" });
      if (res.ok) {
        const body = (await res.json()) as Partial<RuntimeConfig>;
        next = {
          apiBaseUrl:
            typeof body.apiBaseUrl === "string" ? body.apiBaseUrl : "",
          authMode: typeof body.authMode === "string" ? body.authMode : "stub",
        };
      }
    } catch {
      // Network failure: leave the conservative default. resolveUrl()
      // throws on an empty apiBaseUrl, which surfaces as a normal error.
    } finally {
      config = next;
      inFlight = null;
      notify();
    }
    return next;
  })();

  return inFlight;
}

// Synchronous accessors. Return the cached value once resolved; on the
// server they read process.env directly. On the client before the fetch
// resolves they return the conservative default (empty base, stub mode).
export function getApiBaseUrl(): string {
  if (config) return config.apiBaseUrl;
  if (typeof window === "undefined") return process.env.API_BASE_URL ?? "";
  return "";
}

export function getAuthMode(): string {
  if (config) return config.authMode;
  if (typeof window === "undefined") return process.env.AUTH_MODE ?? "stub";
  return "stub";
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): RuntimeConfig | null {
  return config;
}

function getServerSnapshot(): RuntimeConfig | null {
  return null;
}

// Client hook: triggers the one-time fetch and re-renders when it lands.
// `ready` is false until the config resolves; consumers gate on it so a
// client read of authMode never races the fetch.
export function useRuntimeConfig(): {
  config: RuntimeConfig | null;
  ready: boolean;
} {
  const current = useSyncExternalStore(
    subscribe,
    getSnapshot,
    getServerSnapshot,
  );
  useEffect(() => {
    void ensureRuntimeConfig();
  }, []);
  return { config: current, ready: current !== null };
}
