"use client";

import { useQuery } from "@tanstack/react-query";

import { meApi } from "@/lib/api/me";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";

// /me/can-do hook. Intended use: call before a high-stakes action
// where cascade-aware verification matters — avoids the user clicking
// through a UI element only to receive 403 on submit.
//
// Pattern (this hook is the canonical implementation):
//   1. Component mounts, calls useCanDo(module, resource, action,
//      scope, targetAnchor?) — eager react-query fires.
//   2. Cache keyed per-tuple; 60s stale-time dedups same-tuple
//      calls across mounts in the same session.
//   3. Click handler reads `data.allowed` from cache; if false,
//      shows denial toast; if true, proceeds with action.
//
// Known expedient: an in-flight click during /me/can-do load bypasses
// the gate (data is undefined, !== false). Acceptable because
// server-side enforcement is the security boundary. Closing the
// bypass requires button-disable on isLoading (flicker risk) or a
// click-queue (added complexity); deferred until a use case demands
// tighter gating.
//
// Denial is HTTP 200 + allowed:false (NOT 403). 403 only surfaces on
// an actual gated endpoint when the gate rejects. The cache stores
// the boolean answer, not a thrown error.

export function useCanDo(
  module: string,
  resource: string,
  action: string,
  scope: string,
  targetAnchor?: string,
) {
  const snapshot = useAuthSnapshot();
  const userId = snapshot?.user?.userId ?? null;
  const enabled = !!userId;
  return useQuery({
    queryKey: [
      "me",
      "can-do",
      userId,
      module,
      resource,
      action,
      scope,
      targetAnchor ?? null,
    ],
    queryFn: () =>
      meApi.canDo({
        module,
        resource,
        action,
        scope,
        target_anchor: targetAnchor,
      }),
    enabled,
    // Permissions don't change mid-session in v0. 60s stale dedups
    // same-tuple calls across mounts; Infinity would also be fine
    // but 60s preserves the option of in-session re-fetch on persona
    // switch + 401 (AuthBoundary clears the snapshot, which keys the
    // query through `enabled`).
    staleTime: 60_000,
    retry: 1,
  });
}
