"use client";

// POSITION-ALIGNED ARRAY INVARIANT: row.cells[i] under roles[i].
// If you sort/filter rows or roles, MAINTAIN array alignment.
// Mismatched arrays render silently wrong (cells under wrong roles).
// Backend ships pre-sorted; if frontend ever needs different ordering,
// re-shape from scratch rather than mutating in place.

import { useMemo, useState } from "react";

import { Tabs, TabsIndicator, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { PermissionMatrixGroup } from "./PermissionMatrixGroup";
import { usePermissionMatrix } from "@/lib/hooks/use-roles";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import type {
  PermissionMatrixResponse,
  PermissionMatrixRoleColumn,
  PermissionMatrixRow,
} from "@/types/api";

// Phase 5e.2: rewritten to consume Sanjeev's render-ready
// /permission-matrix response. Drops the pre-5e2 15-parallel-detail-
// fetch hack (which built the matrix client-side from 15 parallel
// useQueries on /api/v1/roles/{id}). Backend now ships
// PermissionMatrixResponse with position-aligned cells[i] under
// roles[i] — no client-side construction.
//
// Backend audience filter: TENANT JWTs receive shrunk roles[] +
// shrunk cells[]; the audience tab below is a CLIENT-SIDE partition
// of the already-filtered roles array (so PLATFORM personas can
// switch between viewing Tenant roles vs Platform roles within the
// same loaded grid).

type Audience = "TENANT" | "PLATFORM";

type ResourceGroup = {
  module: string;
  moduleLabel: string;
  resource: string;
  resourceLabel: string;
  // Indices INTO the response.rows[] array — preserving position-
  // alignment with response.roles[] for cell rendering.
  rowIndices: number[];
};

function buildGroups(rows: PermissionMatrixRow[]): ResourceGroup[] {
  // First pass: collect groups in fixture/backend order, keyed by
  // module:resource. Backend ships rows pre-sorted module/resource/
  // action/scope ASC, so we preserve that ordering.
  const byKey = new Map<string, ResourceGroup>();
  rows.forEach((r, idx) => {
    const key = `${r.module}:${r.resource}`;
    let group = byKey.get(key);
    if (!group) {
      group = {
        module: r.module,
        moduleLabel: r.module_label,
        resource: r.resource,
        resourceLabel: r.resource_label,
        rowIndices: [],
      };
      byKey.set(key, group);
    }
    group.rowIndices.push(idx);
  });
  return [...byKey.values()];
}

// Partition role columns by audience. Returns the SAME positional
// indices into response.roles[] so cell projection stays aligned.
function indicesForAudience(
  roles: PermissionMatrixRoleColumn[],
  audience: Audience,
): number[] {
  return roles
    .map((r, i) => ({ role: r, index: i }))
    .filter(({ role }) => role.audience === audience)
    .map(({ index }) => index);
}

// Phase 5g.1.6: module-tab filter constant. "ALL" sentinel renders
// the full matrix (current behavior); a specific module string
// filters resource groups to that module only.
const MODULE_ALL = "ALL";

export function PermissionMatrixView() {
  const matrixQuery = usePermissionMatrix();
  const snapshot = useAuthSnapshot();
  const isTenantPersona = snapshot?.user?.userType === "TENANT";

  const [audience, setAudience] = useState<Audience>("TENANT");
  const [moduleFilter, setModuleFilter] = useState<string>(MODULE_ALL);

  // Default expansion: ADMIN:TENANTS resource (governance-relevant
  // first opener). Keys are unique per module:resource.
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(["ADMIN:TENANTS"]),
  );

  const data: PermissionMatrixResponse | undefined = matrixQuery.data;
  const allGroups = useMemo(() => buildGroups(data?.rows ?? []), [data?.rows]);

  // Distinct module list for the filter tabs, derived from data so
  // future module additions appear automatically. Uses backend's
  // module_label for human-readable tab labels.
  const moduleOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const g of allGroups) {
      if (!seen.has(g.module)) seen.set(g.module, g.moduleLabel);
    }
    return Array.from(seen.entries()).map(([code, label]) => ({ code, label }));
  }, [allGroups]);

  const groups =
    moduleFilter === MODULE_ALL
      ? allGroups
      : allGroups.filter((g) => g.module === moduleFilter);

  if (matrixQuery.isLoading) {
    return (
      <div className="px-6 py-6">
        <Skeleton variant="rect" />
        <div className="mt-4">
          <Skeleton variant="row" count={10} />
        </div>
      </div>
    );
  }

  if (matrixQuery.error || !data) {
    return (
      <div className="px-6 py-6">
        <ErrorInline
          message="Could not load permission matrix."
          onRetry={() => matrixQuery.refetch()}
        />
      </div>
    );
  }

  if (allGroups.length === 0) {
    return (
      <div className="px-6 py-6 text-caption text-foreground-muted">
        No permissions defined.
      </div>
    );
  }

  const tenantIndices = indicesForAudience(data.roles, "TENANT");
  const platformIndices = indicesForAudience(data.roles, "PLATFORM");
  const audienceIndices = audience === "TENANT" ? tenantIndices : platformIndices;
  const audienceRoles = audienceIndices.map((i) => data.roles[i]!);

  // Phase 5g.1.6: hide the "Platform roles" tab for TENANT personas
  // (audience-filter is meaningless when only one audience exists in
  // their grant). PLATFORM keeps both tabs.
  const showAudienceTabs = !isTenantPersona;

  function toggle(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <div className="flex flex-col gap-4 px-6 py-6">
      {showAudienceTabs ? (
        <Tabs
          value={audience}
          onValueChange={(v) => setAudience((v ?? "TENANT") as Audience)}
        >
          <TabsList>
            <TabsIndicator />
            <TabsTrigger value="TENANT">
              Tenant roles ({tenantIndices.length})
            </TabsTrigger>
            <TabsTrigger value="PLATFORM">
              Platform roles ({platformIndices.length})
            </TabsTrigger>
          </TabsList>
        </Tabs>
      ) : null}

      {/* Phase 5g.1.6: module-filter tabs. "All" renders every module
          group (current behavior); per-module tabs constrain visible
          groups to one module — useful when the matrix gets dense
          (ADMIN alone is 23 perms × N roles). */}
      <Tabs
        value={moduleFilter}
        onValueChange={(v) => setModuleFilter(v ?? MODULE_ALL)}
      >
        <TabsList>
          <TabsIndicator />
          <TabsTrigger value={MODULE_ALL}>All</TabsTrigger>
          {moduleOptions.map((m) => (
            <TabsTrigger key={m.code} value={m.code}>
              {m.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {/* Re-key by audience+module so scroll position resets cleanly
          on tab change. */}
      <div
        key={`${audience}:${moduleFilter}`}
        className="relative max-h-[70vh] overflow-auto rounded-md border border-border"
      >
        <table className="w-full border-separate border-spacing-0 text-sm">
          <thead>
            <tr>
              <th
                scope="col"
                className="sticky left-0 top-0 z-30 min-w-[240px] max-w-[240px] border-b border-r border-border bg-card px-3 py-2 text-left text-label text-foreground-muted"
              >
                Permission
              </th>
              {audienceRoles.map((r) => (
                <th
                  key={r.id}
                  scope="col"
                  className="sticky top-0 z-20 min-w-[80px] border-b border-border bg-card px-2 py-2 text-left text-label text-foreground-muted whitespace-nowrap"
                >
                  {r.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {groups.map((group, i) => {
              const key = `${group.module}:${group.resource}`;
              const prevModule = i > 0 ? groups[i - 1]!.module : null;
              const showDivider = prevModule !== group.module;
              return (
                <PermissionMatrixGroup
                  key={key}
                  resource={key}
                  resourceLabel={group.resourceLabel}
                  rows={group.rowIndices.map((idx) => data.rows[idx]!)}
                  rolesInAudience={audienceRoles}
                  audienceIndices={audienceIndices}
                  isExpanded={expanded.has(key)}
                  onToggle={() => toggle(key)}
                  moduleDivider={showDivider ? group.moduleLabel : null}
                />
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
