import type { Persona } from "@/lib/auth/personas";
import type { ModuleCode } from "@/types/api";

import {
  LAUNCHER_TILES,
  unmappedTile,
  type LauncherTileConfig,
  type LauncherTileId,
} from "./tiles";

// My Sevyn8 launcher tile-visibility resolution.
// The launcher trusts the backend's module-access matrix as the sole
// signal for Admin tile visibility (no TENANT Admin carve-out). When
// the matrix has ADMIN: ENABLED for the tenant, the Admin tile
// renders for TENANT same
// as for PLATFORM. Surface-level access control inside Admin remains
// enforced by per-page hasPermission gates + backend RLS.
//
// PLATFORM (Anjali, Kira):
//   - Admin tile: available
//   - DIS tile: available (PLATFORM observes DIS fleet-wide)
//   - All product tiles + Insights + Workforce: Coming Soon
//
// TENANT (Kowalski):
//   - Admin tile: available iff matrix has ADMIN ENABLED for tenant
//                 (same rule as every other product tile).
//   - DIS tile: available if module-access matrix shows DIS ENABLED;
//               hidden if DISABLED.
//   - Each product tile: Coming Soon if ENABLED; hidden if DISABLED.
//   - Insights + Workforce (moduleCode === null): always HIDDEN for
//                          TENANT (forward-looking placeholders not
//                          on the tenant's per-module contract).
//   - An ENABLED module with no tile in this build: a VISIBLY BROKEN
//                          tile naming the code. See below.
//
// Pure function, no React, no hooks. Page composes the inputs from
// useAuthSnapshot + (TENANT) useMyModules.
//
// =========================================================================
// A MODULE WITH NO TILE MUST FAIL VISIBLY
// =========================================================================
// Without the unmapped-tile fallback below, a module granted to a tenant and
// missing from tiles.ts would render nothing at all, and nothing anywhere
// would say so — the same defect class as a defaulted environment variable a
// build check cannot see.
//
// WHY THE COMPILER CANNOT COVER THIS ON ITS OWN, and it is not belt and braces.
// tiles.ts keys its registry by `Record<ModuleCode, ...>`, so a module code
// in the union with no tile is a build failure. But MODULE ACCESS IS DATA: the
// set below is built at runtime from GET /module-access/me, and `ModuleCode` is
// a hand-maintained union in types/api.ts. The server can return a module_code
// that union has never contained, on an image that shipped weeks earlier. The
// declared type of `enabledModules` says that cannot happen; the wire says
// otherwise, and the wire wins. So the check is here, at runtime, where the
// value actually arrives.
//
// THIS IS NOT AN ALERT AND IS NOT WIRED TO ONE. The tenant sees it; Sevyn8 does
// not. A reporting path was deliberately left out, and the gap is stated
// rather than implied.

export type TileState = "available" | "coming-soon" | "unmapped";

export type ResolvedTile = LauncherTileConfig & {
  state: TileState;
};

export function getVisibleTiles(
  persona: Persona,
  // The set of module codes ENABLED for the TENANT persona's own tenant
  // (sourced from GET /module-access/me). Ignored for PLATFORM
  // personas, whose tiles are static. Empty while the query loads.
  //
  // TYPED AS ModuleCode AND NOT TRUSTED AS ONE. See the header: this is
  // server data, and the type is a claim about it rather than a constraint on it.
  enabledModules: ReadonlySet<ModuleCode>,
): ResolvedTile[] {
  if (persona.userType === "PLATFORM") {
    return LAUNCHER_TILES.map((t) => ({
      ...t,
      state:
        t.id === "admin" || t.id === "dis"
          ? ("available" as const)
          : ("coming-soon" as const),
    }));
  }

  // TENANT path. Gate every tile by the tenant's enabled module set.
  const resolved: ResolvedTile[] = [];
  const covered = new Set<string>();

  for (const t of LAUNCHER_TILES) {
    if (t.moduleCode === null) {
      // DECLARED INTENT, NOT A MISSING CASE. Insights and Workforce are
      // forward-looking placeholders that sit on no tenant's per-module
      // contract, so a tenant never sees them. tiles.ts keeps them in their own
      // array so this branch cannot quietly acquire a second meaning.
      continue;
    }

    covered.add(t.moduleCode);

    if (!enabledModules.has(t.moduleCode)) {
      // NOT ENABLED FOR THIS TENANT, which is the module-access matrix doing
      // exactly its job. Distinct from both branches around it.
      continue;
    }

    if (t.id === "dis" || t.id === "admin") {
      // DIS + Admin: backend module-access matrix is the authoritative
      // gate. Matrix says ENABLED, so a real link; per-surface guards
      // inside the product enforce finer-grained access.
      resolved.push({ ...t, state: "available" as const });
    } else {
      // Product modules: enabled means Coming Soon (modules ship later)
      resolved.push({ ...t, state: "coming-soon" as const });
    }
  }

  // THE MISSING CASE, MADE LOUD. Anything the tenant is entitled to that this
  // build cannot render gets a tile saying so, rather than vanishing.
  for (const code of enabledModules) {
    if (!covered.has(code)) {
      resolved.push({ ...unmappedTile(code), state: "unmapped" as const });
    }
  }

  return resolved;
}

// Re-export ids for e2e + page consumers.
export type { LauncherTileId };
