"use client";

import { useEffect, useRef, useSyncExternalStore, type ReactNode } from "react";
import { useRouter } from "next/navigation";

import { setAuthSnapshot } from "@/lib/auth/auth-cache";
import {
  clearCurrentPersona,
  getAuthStateKey,
  getAuthToken,
  isAuthTokenResolved,
  prefetchAuthToken,
  subscribeAuthChange,
} from "@/lib/auth/getAuthToken";
import { decodeJwtClaims } from "@/lib/auth/jwt-decode";
import { buildPersonaFromClaims } from "@/lib/auth/persona-from-claims";
import { useMePermissions } from "@/lib/auth/use-me-permissions";
import { isPersonaId, type PersonaId } from "@/lib/auth/personas";
import { ApiError } from "@/lib/api/client";

const PERSONA_STORAGE_KEY = "ithina:dev-persona";

function readStoredPersonaId(): PersonaId | null {
  if (typeof window === "undefined") return null;
  const stored = window.localStorage.getItem(PERSONA_STORAGE_KEY);
  return isPersonaId(stored) ? stored : null;
}

function getServerSnapshot(): PersonaId | null {
  return null;
}

function getServerKey(): string {
  return "ssr";
}

// Phase 5f.W.1: AuthBoundary refactored to drive the JWT-decode +
// /me/permissions cache flow. Replaces the pre-5f.W findPersonaById
// catalogue lookup.
//
// Flow:
//   1. Read dev persona id from localStorage (sync external store).
//   2. Read JWT from getAuthToken() — keyed on dev persona id.
//   3. Decode JWT claims → build Persona (claims + optional dev seed
//      for display name).
//   4. Fire useMePermissions(persona.userId) → /me/permissions.
//   5. setAuthSnapshot({user, permissions}) once both are settled.
//   6. On 401 from the permissions fetch: clear persona + redirect.
//   7. On missing/invalid JWT: clear persona + redirect.

export function AuthBoundary({ children }: { children: ReactNode }) {
  const router = useRouter();
  const personaId = useSyncExternalStore(
    subscribeAuthChange,
    readStoredPersonaId,
    getServerSnapshot,
  );
  // Re-render when the active persona's token resolves (the prefetch is
  // async). Without this the token would read null on first render and
  // the redirect effect below would bounce to /dev/login before the
  // fetch lands. The returned key is consumed only for its identity.
  useSyncExternalStore(subscribeAuthChange, getAuthStateKey, getServerKey);

  // Warm the token cache for the stored persona on load (and on switch).
  useEffect(() => {
    if (personaId) void prefetchAuthToken(personaId);
  }, [personaId]);

  // Decode the JWT for the active persona. null when no persona is
  // set, no JWT is configured (e.g. Kira), the token is still in
  // flight, or the JWT shape is malformed.
  const token = typeof window === "undefined" ? null : getAuthToken();
  const claims = decodeJwtClaims(token);
  const persona = claims ? buildPersonaFromClaims(claims, personaId) : null;
  const tokenResolved =
    typeof window !== "undefined" && personaId != null && isAuthTokenResolved();

  const permissionsQuery = useMePermissions(persona?.userId ?? null);

  // Phase 5h.5 introduced `queryClient.clear()` here on userId
  // transitions as belt-and-suspenders to Finding #50's userId-in-
  // queryKey isolation. Phase 5i.1.1 (2026-05-25) reverted the
  // .clear() call — in persistent sessions it was wiping the
  // /me/permissions cache mid-flight, which surfaced to AuthBoundary
  // as "unauthenticated" and bounced the user back to /dev/login on
  // every persona pick. Incognito did not reproduce because
  // prevUserIdRef.current starts null on a fresh mount and the
  // guarded clear never fired.
  //
  // The userId-in-key isolation (Finding #50) IS the actual cache-
  // bleed prevention mechanism and is sufficient on its own. The
  // ref-tracking scaffolding is kept so the Auth0 logout flow can
  // attach explicit session-end semantics here (then we have an
  // unambiguous trigger, not transition detection on a value that
  // can spuriously transition during normal session refresh).
  const prevUserIdRef = useRef<string | null>(null);
  useEffect(() => {
    const currentUserId = persona?.userId ?? null;
    if (currentUserId !== null) {
      prevUserIdRef.current = currentUserId;
    }
  }, [persona?.userId]);

  // Side effects: populate the AuthSnapshot cache + redirect on
  // missing-persona or 401 from /me/permissions.
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!personaId) {
      setAuthSnapshot(null);
      router.replace("/dev/login");
      return;
    }
    // Persona is set but its token is still being fetched from
    // /api/dev-token. Wait (the loading gate below renders) rather than
    // bouncing to /dev/login on a transiently-null token.
    if (!tokenResolved) {
      return;
    }
    if (!persona) {
      // Token resolved but no valid JWT for this persona → no session.
      setAuthSnapshot(null);
      router.replace("/dev/login");
      return;
    }
    // 401 from /me/permissions → JWT is invalid or rejected by backend.
    // Clear the dev persona (which clears the JWT) and bounce to login.
    if (
      permissionsQuery.error instanceof ApiError &&
      permissionsQuery.error.status === 401
    ) {
      clearCurrentPersona();
      setAuthSnapshot(null);
      router.replace("/dev/login");
      return;
    }
    setAuthSnapshot({
      user: persona,
      // null while in flight; null on error (other than 401, which
      // redirects above). Consumers should render conservatively
      // when permissions are null.
      permissions: permissionsQuery.data?.permissions ?? null,
    });
  }, [
    personaId,
    persona,
    tokenResolved,
    permissionsQuery.error,
    permissionsQuery.data,
    router,
  ]);

  if (!persona) {
    return (
      <div className="flex h-screen w-screen items-center justify-center text-sm text-muted-foreground">
        Loading session…
      </div>
    );
  }

  return <>{children}</>;
}
