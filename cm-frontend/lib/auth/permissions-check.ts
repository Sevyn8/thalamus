import type { AuthSnapshot } from "@/lib/auth/auth-cache";

// Synchronous permission gate reading from the cached
// /me/permissions grant list (populated by AuthBoundary at boot).
//
// Backend is the single source of truth for grants. UI primitives
// (sidebar items, tab visibility, page guards, dashboard cards) gate
// on `hasPermission`; cascade-aware click-time pre-flight on
// high-stakes actions continues to route through `useCanDo`.
//
// Fail-closed: if `snapshot` or `snapshot.permissions` is null (boot
// in flight, or /me/permissions failed), the helper returns false.
// Consumers should accept this — surfacing nothing during boot is
// strictly better than surfacing a control the backend would reject.

export type PermissionScope = "GLOBAL" | "TENANT" | "STORE";

/**
 * Returns true if the cached grant list contains a tuple matching
 * (module, resource, action[, scope]). When `scope` is omitted, any
 * scope matches — useful for "user can see X surface" gates where
 * the scope of access is the backend's concern.
 */
export function hasPermission(
  snapshot: AuthSnapshot | null,
  module: string,
  resource: string,
  action: string,
  scope?: PermissionScope,
): boolean {
  if (!snapshot?.permissions) return false;
  return snapshot.permissions.some(
    (p) =>
      p.module === module &&
      p.resource === resource &&
      p.action === action &&
      (scope === undefined || p.scope === scope),
  );
}

/**
 * Convenience alias: "does the caller hold (module, resource, action)
 * in any scope?" Semantically equivalent to `hasPermission` without
 * the scope argument; named explicitly to make the intent legible at
 * the call site.
 */
export function hasAnyScope(
  snapshot: AuthSnapshot | null,
  module: string,
  resource: string,
  action: string,
): boolean {
  return hasPermission(snapshot, module, resource, action);
}
