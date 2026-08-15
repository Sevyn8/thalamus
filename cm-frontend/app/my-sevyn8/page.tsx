"use client";

import { useMemo } from "react";

import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { useMyModules } from "@/lib/hooks/use-modules";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { IthinaLogo } from "@/components/chrome/IthinaLogo";
import { LauncherTile } from "@/components/launcher/LauncherTile";
import { getVisibleTiles } from "@/lib/launcher/visibility";
import {
  getFirstName,
  getTimeOfDayGreeting,
} from "@/lib/format/greeting";
import type { ModuleCode } from "@/types/api";

// Phase 5d.1: My Sevyn8 launcher. 3-column tile grid; tiles
// resolve per persona via getVisibleTiles.
//
// PLATFORM personas see the full 9-tile shape (Admin + DIS
// available; 7 placeholders Coming Soon) with no per-tenant fetch.
// TENANT personas see only the modules enabled for their own tenant,
// read via the tenant-scoped GET /module-access/me (Slice 8). The
// admin matrix endpoint is gated on ADMIN.TENANTS.VIEW.TENANT and
// would 403 a tenant user without that governance grant.
//
// Loading shape: skeleton placeholders matching tile dimensions so
// the layout doesn't jump when the query resolves.

export default function MyIthinaPage() {
  const snapshot = useAuthSnapshot();
  const persona = snapshot?.user ?? null;
  const isTenantPersona = persona?.userType === "TENANT";

  // Only TENANT personas need the per-tenant module read; PLATFORM
  // tiles are static.
  const myModules = useMyModules({ enabled: isTenantPersona });
  const modulesLoading = isTenantPersona && myModules.isLoading;
  const modulesError = isTenantPersona && myModules.error;

  const enabledModules = useMemo(() => {
    const set = new Set<ModuleCode>();
    if (isTenantPersona && myModules.data) {
      for (const m of myModules.data.modules) {
        if (m.status === "ENABLED") set.add(m.module_code);
      }
    }
    return set;
  }, [isTenantPersona, myModules.data]);

  const tiles = useMemo(() => {
    if (!persona) return [];
    if (isTenantPersona && !myModules.data) return [];
    return getVisibleTiles(persona, enabledModules);
  }, [persona, isTenantPersona, myModules.data, enabledModules]);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-8 px-6 py-12">
      <div className="flex flex-col gap-3">
        <IthinaLogo size={48} />
        {/* Phase 5d.9: greeting replaces the prior "My Sevyn8"
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
      ) : modulesError ? (
        <ErrorInline message="Failed to load workspace access." />
      ) : modulesLoading ? (
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
