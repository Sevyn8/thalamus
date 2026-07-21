"use client";

import { useEffect, useSyncExternalStore, type ReactNode } from "react";
import { useUser } from "@auth0/nextjs-auth0";

import { setAuthSnapshot } from "@/lib/auth/auth-cache";
import {
  getAuthStateKey,
  prefetchAuthToken,
  subscribeAuthChange,
} from "@/lib/auth/getAuthToken";
import { claimsFromSessionUser } from "@/lib/auth/jwt-decode";
import { buildPersonaFromClaims } from "@/lib/auth/persona-from-claims";
import { useMePermissions } from "@/lib/auth/use-me-permissions";

function getServerKey(): string {
  return "ssr";
}

// Session gate for authenticated layouts. The middleware (proxy.ts) already
// redirects unauthenticated requests to /auth/login, so by the time this
// renders a session should exist; useUser() surfaces the identity claims.
//
// Flow:
//   1. useUser() -> the Auth0 session user (namespaced https://sevyn8.com/*
//      claims), built into the Persona the UI expects.
//   2. prefetchAuthToken() warms the BFF token cache (/api/access-token) so
//      client.ts has a Bearer for cm-backend calls.
//   3. useMePermissions(userId) -> /me/permissions.
//   4. setAuthSnapshot({user, permissions}) once settled.
//   5. On 401 from permissions: send to /auth/logout (session invalid).

export function AuthBoundary({ children }: { children: ReactNode }) {
  const { user, isLoading } = useUser();

  // Re-render when the BFF token resolves (the prefetch is async).
  useSyncExternalStore(subscribeAuthChange, getAuthStateKey, getServerKey);

  const claims = claimsFromSessionUser(user as Record<string, unknown> | null | undefined);
  const persona = claims ? buildPersonaFromClaims(claims) : null;

  // Warm the BFF access-token cache once we have a session.
  useEffect(() => {
    if (persona) void prefetchAuthToken();
  }, [persona]);

  const permissionsQuery = useMePermissions(persona?.userId ?? null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!persona) {
      setAuthSnapshot(null);
      return;
    }
    // 401 from /me/permissions -> the session/token is rejected by cm-backend.
    // End the session via the SDK logout route.
    const status = (permissionsQuery.error as { status?: number } | null)?.status;
    if (status === 401) {
      setAuthSnapshot(null);
      window.location.href = "/auth/logout";
      return;
    }
    setAuthSnapshot({
      user: persona,
      permissions: permissionsQuery.data?.permissions ?? null,
    });
  }, [persona, permissionsQuery.error, permissionsQuery.data]);

  // While the session is loading (or claims are not yet available), gate.
  if (isLoading || !persona) {
    return (
      <div className="flex h-screen w-screen items-center justify-center text-sm text-muted-foreground">
        Loading session…
      </div>
    );
  }

  return <>{children}</>;
}
