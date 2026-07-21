import { useEffect, useSyncExternalStore } from "react";

// Runtime config store. Decouples the API base URL from build time: the client
// learns it from /api/config (a force-dynamic route that reads non-prefixed
// server env at request time), so the same image can be promoted across
// projects without a rebuild. Server-side callers read process.env directly.

export type RuntimeConfig = {
  apiBaseUrl: string;
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
  };
}

// Fetch + cache the runtime config exactly once. Concurrent callers share the
// same in-flight promise. On the server the value comes straight from
// process.env (no /api/config round-trip). Safe to await repeatedly.
export async function ensureRuntimeConfig(): Promise<RuntimeConfig> {
  if (config) return config;

  if (typeof window === "undefined") {
    config = readServerConfig();
    return config;
  }

  if (inFlight) return inFlight;

  inFlight = (async () => {
    let next: RuntimeConfig = { apiBaseUrl: "" };
    try {
      const res = await fetch(CONFIG_ENDPOINT, { credentials: "omit" });
      if (res.ok) {
        const body = (await res.json()) as Partial<RuntimeConfig>;
        next = {
          apiBaseUrl:
            typeof body.apiBaseUrl === "string" ? body.apiBaseUrl : "",
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

// Synchronous accessor. Returns the cached value once resolved; on the server
// reads process.env directly; on the client before the fetch resolves returns
// the conservative default (empty base).
export function getApiBaseUrl(): string {
  if (config) return config.apiBaseUrl;
  if (typeof window === "undefined") return process.env.API_BASE_URL ?? "";
  return "";
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
