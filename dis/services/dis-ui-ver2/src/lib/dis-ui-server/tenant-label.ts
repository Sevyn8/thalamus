// Shared tenant attribution display (Chunk 2-attribution + Chunk 3 fleet columns). PLATFORM/ops
// surfaces show the owning tenant of each cross-tenant row. As of Chunk 9 the backend serves a
// mirrored ``tenant_name``, so ``tenantName`` DISPLAYS that name when present and HONESTLY falls
// back to the shortened UUID (``tenantShort``) when absent/null — NEVER a fabricated friendly name.
// Used by the Needs-attention triage view AND the four fleet surfaces (Ingestion Runs, Connector
// Health, Sources, Audit), so the labelling + null-tenant handling stay identical everywhere.

// Sentinel value for the null-tenant ("System / platform") option/group in a tenant filter (a real
// tenant_id is a UUID, never this string), so a filter <select> can carry it as an option value.
export const SYSTEM_TENANT = ' system'

// Shortened display: the entropy-bearing UUID TAIL. UUIDv7 shares a leading time-prefix across
// tenants, so a head slice would collide; the tail carries the random bits. Full id goes in the
// title/tooltip. A null tenant_id (audit system rows under PLATFORM see-all) renders "System /
// platform".
export function tenantShort(tenantId: string | null): string {
  return tenantId === null ? 'System / platform' : `…${tenantId.slice(-12)}`
}

// The DISPLAY label for a tenant (Chunk 9-FE): the mirrored ``tenant_name`` when the backend serves
// one (identity_mirror.tenants.name), else an HONEST fallback to the shortened UUID — NEVER a
// fabricated name. Optional/absent (an older backend that predates Chunk 9) and null/empty both
// fall back. The full UUID still belongs in the title/tooltip (``tenantFull``). A null tenant_id
// (audit system rows) falls through to ``tenantShort`` → "System / platform" (unchanged).
export function tenantName(name: string | null | undefined, tenantId: string | null): string {
  const trimmed = typeof name === 'string' ? name.trim() : ''
  return trimmed !== '' ? trimmed : tenantShort(tenantId)
}

// The full, unambiguous tenant identity for a title/tooltip (the raw UUID, or a system marker).
export function tenantFull(tenantId: string | null): string {
  return tenantId ?? 'system / platform (no tenant)'
}

// Distinct tenant_ids present in a fetched row set, for AUTO-POPULATING a tenant filter (no
// hardcoded list). Sorted; the null-tenant (system) entry sorts last.
export function distinctTenants(tenantIds: (string | null)[]): (string | null)[] {
  return [...new Set(tenantIds)].sort((a, b) => (a === null ? 1 : b === null ? -1 : a.localeCompare(b)))
}

// Does a row's tenant_id match the active tenant filter? `filter` null = no filter (all pass);
// SYSTEM_TENANT matches the null-tenant (system) rows; otherwise an exact tenant_id match.
export function matchesTenant(tenantId: string | null, filter: string | null): boolean {
  if (filter === null) return true
  return filter === SYSTEM_TENANT ? tenantId === null : tenantId === filter
}
