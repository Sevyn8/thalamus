"use client";

import { useQuery } from "@tanstack/react-query";

import { meApi } from "@/lib/api/me";

// Phase 5f.W.1: /me/permissions cache. Per Sanjeev's design intent
// (docs/endpoints/me.md): "call once at login or session refresh;
// cache the result client-side and use it to gate UI elements."
//
// Cache keyed on the caller's userId so a session change triggers a
// fresh fetch automatically (react-query treats the key change as a
// new query). Invalidation on 401 happens at AuthBoundary, which
// clears AuthSnapshot + ends the session via /auth/logout; the query's
// stale cache stays in react-query but isn't consumed once Persona is null.

export function useMePermissions(userId: string | null) {
  return useQuery({
    queryKey: ["me", "permissions", userId],
    queryFn: () => meApi.permissions(),
    enabled: typeof userId === "string" && userId.length > 0,
    // Permissions don't change mid-session — backend re-issues on
    // grant change via JWT refresh (Auth Phase 2). v0 keeps the cache
    // long; the AuthBoundary invalidates on persona switch + 401.
    staleTime: Infinity,
    retry: 1,
  });
}
