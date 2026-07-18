import type { Persona } from "@/lib/auth/personas";
import type { MatrixRow, ModuleCode } from "@/types/api";

import {
  LAUNCHER_TILES,
  type LauncherTileConfig,
  type LauncherTileId,
} from "./tiles";

// Phase 5d.1: My Ithina launcher tile-visibility resolution.
// Phase 5g.1: TENANT Admin carve-out removed — the launcher now
// trusts the backend's module-access matrix as the sole signal for
// Admin tile visibility (Finding #17 closed). When matrix has
// ADMIN: ENABLED for the tenant, Admin tile renders for TENANT same
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
//
// Pure function — no React, no hooks. Page composes the inputs from
// useAuthSnapshot + useModuleMatrix.

export type ResolvedTile = LauncherTileConfig & {
  state: "available" | "coming-soon";
};

export function getVisibleTiles(
  persona: Persona,
  // The TENANT persona's matrix row, if available. null for PLATFORM
  // (no per-tenant gating needed) or while the matrix query is loading.
  tenantRow: MatrixRow | null,
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

  // TENANT path. Hide Admin entirely; gate the rest by matrix cells.
  // Phase 5f.V: cast widening retired. MatrixCell.module_code is now
  // narrowed to the hand-maintained ModuleCode union (via the
  // Omit<>&{} bridge in types/api.ts), so Set<ModuleCode> takes the
  // values directly. See types/api.ts ModuleCode awaited-debt comment
  // for the DIS hand-extension rationale.
  const enabledModules = new Set<ModuleCode>(
    (tenantRow?.cells ?? [])
      .filter((c) => c.status === "ENABLED")
      .map((c) => c.module_code),
  );

  return LAUNCHER_TILES.flatMap<ResolvedTile>((t) => {
    if (t.moduleCode === null) return []; // Insights / Workforce
    if (!enabledModules.has(t.moduleCode)) return [];
    if (t.id === "dis" || t.id === "admin") {
      // DIS + Admin: backend module-access matrix is the authoritative
      // gate. Matrix says ENABLED → real link; per-surface guards
      // inside the product enforce finer-grained access.
      return [{ ...t, state: "available" as const }];
    }
    // Product modules: enabled → Coming Soon (modules ship later)
    return [{ ...t, state: "coming-soon" as const }];
  });
}

// Re-export ids for e2e + page consumers.
export type { LauncherTileId };
