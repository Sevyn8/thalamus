import { useSyncExternalStore } from "react";

import type { Persona } from "./personas";
import type { components } from "@/types/openapi-generated";
import { subscribeAuthChange } from "./getAuthToken";

// AuthSnapshot carries the permissions cache from /me/permissions.
// Populated by AuthBoundary at boot; consumed by useAuthSnapshot()
// across the app. Server-side enforcement is the security boundary —
// these permissions are UI hints only.

export type PermissionGrantRead =
  components["schemas"]["PermissionGrantRead"];

export type AuthSnapshot = {
  user: Persona;
  // null while /me/permissions is in flight or has failed; consumers
  // should treat null as "permissions unknown, render conservatively"
  // until the cache populates.
  permissions: PermissionGrantRead[] | null;
};

let snapshot: AuthSnapshot | null = null;

export function setAuthSnapshot(next: AuthSnapshot | null): void {
  snapshot = next;
  notify();
}

export function getAuthSnapshot(): AuthSnapshot | null {
  return snapshot;
}

const cacheListeners = new Set<() => void>();

function notify(): void {
  for (const fn of cacheListeners) fn();
}

function subscribe(listener: () => void): () => void {
  cacheListeners.add(listener);
  // Also relay token-side changes so consumers re-render when persona
  // switches via the localStorage path (e.g. from another tab).
  const unsubToken = subscribeAuthChange(listener);
  return () => {
    cacheListeners.delete(listener);
    unsubToken();
  };
}

const getServerSnapshot = (): AuthSnapshot | null => null;

export function useAuthSnapshot(): AuthSnapshot | null {
  return useSyncExternalStore(subscribe, () => snapshot, getServerSnapshot);
}
