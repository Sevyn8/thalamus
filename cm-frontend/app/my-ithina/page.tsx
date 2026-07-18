"use client";

import { useMemo } from "react";

import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { useModuleMatrix } from "@/lib/hooks/use-modules";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { IthinaLogo } from "@/components/chrome/IthinaLogo";
import { LauncherTile } from "@/components/launcher/LauncherTile";
import { getVisibleTiles } from "@/lib/launcher/visibility";
import {
  getFirstName,
  getTimeOfDayGreeting,
} from "@/lib/format/greeting";
import type { MatrixResponse } from "@/types/api";
import type { Persona } from "@/lib/auth/personas";

// Resolves the TENANT persona's matrix row across both deploy modes:
//
//   Real backend (RLS): the matrix endpoint returns a single row
//     scoped to the JWT's tenant_id. Use it directly.
//
//   MSW (no RLS simulation per modules.ts handler comment): all
//     non-TERMINATED tenant rows return. Find the user's row by
//     direct tenant_id match. Phase 5f.X consolidated to a single
//     canonical Sanjeev UUID namespace; the prior DIS-side vs
//     Ithina-side alias bridge and " Group" suffix-stripping
//     fallback both retired.
function findTenantRow(matrix: MatrixResponse, persona: Persona) {
  const items = matrix.items;
  if (items.length === 1) return items[0] ?? null;
  if (persona.tenantId) {
    return items.find((r) => r.tenant_id === persona.tenantId) ?? null;
  }
  return null;
}

// Phase 5d.1: My Ithina launcher. 3-column tile grid; tiles
// resolve per persona via getVisibleTiles.
//
// PLATFORM personas see the full 9-tile shape (Admin + DIS
// available; 7 placeholders Coming Soon). TENANT personas see
// only the modules enabled for their tenant per the module-access
// matrix.
//
// Loading shape: skeleton placeholders matching tile dimensions so
// the layout doesn't jump when the matrix query resolves.

export default function MyIthinaPage() {
  const snapshot = useAuthSnapshot();
  const persona = snapshot?.user ?? null;
  const isTenantPersona = persona?.userType === "TENANT";

  const matrix = useModuleMatrix(undefined);
  const matrixLoading = isTenantPersona && matrix.isLoading;
  const matrixError = isTenantPersona && matrix.error;

  const tenantRow = useMemo(() => {
    if (!isTenantPersona || !persona || !matrix.data) return null;
    return findTenantRow(matrix.data, persona);
  }, [isTenantPersona, persona, matrix.data]);

  const tiles = useMemo(() => {
    if (!persona) return [];
    if (isTenantPersona && !matrix.data) return [];
    return getVisibleTiles(persona, tenantRow);
  }, [persona, isTenantPersona, matrix.data, tenantRow]);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-8 px-6 py-12">
      <div className="flex flex-col gap-3">
        <IthinaLogo size={48} />
        {/* Phase 5d.9: greeting replaces the prior "My Ithina"
            heading. Brand identity carries via logo + URL/tab
            title; the heading personalizes. Time-aware prefix +
            first-name extraction (with initial-style fallback to
            full name) live in lib/format/greeting.ts. */}
        <h1 className="text-display">
          {(() => {
            const prefix = getTimeOfDayGreeting(new Date());
            const firstName = persona ? getFirstName(persona) : null;
            return firstName
              ? `${prefix}, ${firstName}`
              : prefix;
          })()}
        </h1>
      </div>

      {!persona ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} variant="card" className="h-40 w-full" />
          ))}
        </div>
      ) : matrixError ? (
        <ErrorInline message="Failed to load workspace access." />
      ) : matrixLoading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} variant="card" className="h-40 w-full" />
          ))}
        </div>
      ) : tiles.length === 0 ? (
        <div className="rounded-md border border-border bg-card p-6 text-body text-foreground-muted">
          No workspaces enabled for your tenant. Contact your administrator.
        </div>
      ) : (
        <ul
          aria-label="Available workspaces"
          className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
        >
          {tiles.map((tile) => (
            <li key={tile.id}>
              <LauncherTile
                id={tile.id}
                icon={tile.icon}
                name={tile.name}
                description={tile.description}
                state={tile.state}
                href={tile.href ?? undefined}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
