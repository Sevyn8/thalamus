import type { AuditEventRow } from './audit'
import type { ConnectorHealthRow } from './connector-health'
import type { QuarantineListResponse } from './quarantine-api'
import type { RunRow } from './runs'
import { SYSTEM_TENANT } from './tenant-label'

// Re-exported so existing importers (NotificationsRoute, this module's tests) keep resolving it
// here; the canonical definition now lives in the shared tenant-label util (Chunk 3).
export { SYSTEM_TENANT }

// "Needs attention" — a READ-ONLY, STATELESS derived feed. It recomputes on load from FOUR
// existing endpoints (runs, connector-health, quarantine, audit); it holds NO read/ack/severity
// state and mints NO new backend. Tenant token → per-tenant items; PLATFORM token → the same
// endpoints see-all, and (since Chunk 1 added tenant_id to the rows) the items are ATTRIBUTED to
// their owning tenant and grouped per-tenant in the fleet view (see groupByTenant).
//
// SEVERITY is a FRONTEND-DERIVED DISPLAY ORDER, not a backend field: no endpoint returns a
// severity/priority. error (failed run / audit failure) > warning (stale/pending/auth-expiring
// connector, quarantine backlog, partial run) > info (rate-limited). Used only to sort + badge.

export type AttentionSeverity = 'error' | 'warning' | 'info'
export const SEVERITY_RANK: Record<AttentionSeverity, number> = { error: 0, warning: 1, info: 2 }

export type AttentionSource = 'runs' | 'connector' | 'quarantine' | 'audit'

// A deep-link to an EXISTING ver2 route (no new routes). The label is the drawer action verb.
export type AttentionLink = { to: string; label: string }

export type AttentionDetailRow = { label: string; value: string }

export type AttentionItem = {
  id: string
  source: AttentionSource
  // The owning tenant (Chunk 1). A UUID string; null only for audit system rows (tenant_id IS
  // NULL under PLATFORM see-all). Drives the PLATFORM per-tenant grouping. NEVER a friendly name
  // (tenant_name is Chunk 9) — the UI shows the UUID (shortened + full in title/tooltip).
  tenant_id: string | null
  // Chunk 9: the owning tenant's mirrored name (identity_mirror.tenants.name) when the source row
  // carried one; absent/null → the UI (via tenantName) falls back to the shortened UUID. Never
  // fabricated. Propagated from each source row by the deriveFrom* functions below.
  tenant_name?: string | null
  severity: AttentionSeverity
  // The STABLE type label (the "Type" filter key + display). Distinct from `title`, which may carry
  // a count (quarantine → "N rows quarantined"); typeLabel is count-free ("Quarantine backlog") so
  // filtering by type is stable. Auto-populated into the Type filter from the distinct values present.
  typeLabel: string
  title: string
  context: string // one-line: source · when (row subtitle)
  at: string | null // ISO for recency sort; null (e.g. quarantine backlog) sorts last within severity
  link: AttentionLink // the drawer's deep-link action (existing route only)
  detail: AttentionDetailRow[] // key/value rows shown in the drawer body
}

// Deep-links — existing ver2 routes only (AppRoutes): /ingestion-runs, /connector-health,
// /data-quality, /audit. NOTE: these link to the SURFACE (list); opening the exact row's
// slide-over across routes is not wired (the target surfaces own their own drawers).
const RUNS_LINK: AttentionLink = { to: '/ingestion-runs', label: 'View run' }
const CONNECTOR_LINK: AttentionLink = { to: '/connector-health', label: 'Fix connector' }
const QUARANTINE_LINK: AttentionLink = { to: '/data-quality', label: 'Review queue' }
const AUDIT_LINK: AttentionLink = { to: '/audit', label: 'View in audit' }

function orDash(n: number | null): string {
  return n !== null ? n.toLocaleString() : '—'
}

// 1. Runs: verdict=failed → error; verdict=quarantined OR accepted<input (partial) → warning.
// One item per run (failed takes precedence over the quarantined/partial branch).
export function deriveFromRuns(rows: RunRow[]): AttentionItem[] {
  const items: AttentionItem[] = []
  for (const r of rows) {
    const source = r.source_name ?? r.source_id
    const partial = r.accepted !== null && r.input_row_count !== null && r.accepted < r.input_row_count
    if (r.status === 'failed') {
      items.push({
        id: `run:${r.id}`,
        source: 'runs',
        tenant_id: r.tenant_id,
        tenant_name: r.tenant_name ?? null, // Chunk 9
        severity: 'error',
        typeLabel: 'Run failed',
        title: 'Run failed',
        context: `${source} · ${r.received_at}`,
        at: r.received_at,
        link: RUNS_LINK,
        detail: [
          { label: 'Run', value: r.id.slice(0, 8) },
          { label: 'Source', value: source },
          { label: 'Verdict', value: 'failed' },
          { label: 'Input rows', value: orDash(r.input_row_count) },
          { label: 'Received', value: r.received_at },
        ],
      })
    } else if (r.status === 'quarantined' || partial) {
      items.push({
        id: `run:${r.id}`,
        source: 'runs',
        tenant_id: r.tenant_id,
        tenant_name: r.tenant_name ?? null, // Chunk 9
        severity: 'warning',
        typeLabel: r.status === 'quarantined' ? 'Run quarantined' : 'Run partially accepted',
        title: r.status === 'quarantined' ? 'Run quarantined' : 'Run partially accepted',
        context: `${source} · ${r.received_at}`,
        at: r.received_at,
        link: RUNS_LINK,
        detail: [
          { label: 'Run', value: r.id.slice(0, 8) },
          { label: 'Source', value: source },
          { label: 'Accepted', value: orDash(r.accepted) },
          { label: 'Input rows', value: orDash(r.input_row_count) },
          { label: 'Quarantined', value: orDash(r.quarantined) },
        ],
      })
    }
  }
  return items
}

// 2. Connector health: stale/pending → warning; auth_expiring → warning; rate_limited → info.
// healthy → not an attention item.
export function deriveFromConnectors(rows: ConnectorHealthRow[]): AttentionItem[] {
  const items: AttentionItem[] = []
  for (const c of rows) {
    let severity: AttentionSeverity
    let title: string
    if (c.status === 'stale' || c.status === 'pending') {
      severity = 'warning'
      title = c.status === 'stale' ? 'Connector stale' : 'Connector pending'
    } else if (c.status === 'auth_expiring') {
      severity = 'warning'
      title = 'Auth expiring'
    } else if (c.status === 'rate_limited') {
      severity = 'info'
      title = 'Rate-limited'
    } else {
      continue // healthy
    }
    items.push({
      id: `connector:${c.source_id}`,
      source: 'connector',
      tenant_id: c.tenant_id,
      tenant_name: c.tenant_name ?? null, // Chunk 9
      severity,
      typeLabel: title, // connector titles are stable (Connector stale / Auth expiring / …)
      title,
      context: `${c.display_name} · ${c.status}`,
      at: c.auth_expires_at ?? c.last_seen_at,
      link: CONNECTOR_LINK,
      detail: [
        { label: 'Connector', value: c.display_name },
        { label: 'Status', value: c.status },
        { label: 'Last seen', value: c.last_seen_at ?? '—' },
        { label: 'Auth expires', value: c.auth_expires_at ?? '—' },
        { label: 'Rate limit', value: c.rate_limit_state ?? '—' },
      ],
    })
  }
  return items
}

// 3. Audit: outcome=failure rows → error ("Ingestion failure"). Filters defensively even though
// the route requests outcome=failure (so the fetch is already scoped).
export function deriveFromAudit(rows: AuditEventRow[]): AttentionItem[] {
  return rows
    .filter((r) => r.outcome === 'failure')
    .map((r) => ({
      id: `audit:${r.id}`,
      source: 'audit' as const,
      tenant_id: r.tenant_id, // str | null — null system rows group under "System / platform"
      tenant_name: r.tenant_name ?? null, // Chunk 9
      severity: 'error' as const,
      typeLabel: 'Ingestion failure',
      title: 'Ingestion failure',
      context: `${r.stage} · ${r.event_timestamp}`,
      at: r.event_timestamp,
      link: AUDIT_LINK,
      detail: [
        { label: 'Stage', value: r.stage },
        { label: 'Trace', value: r.trace_id.slice(0, 8) },
        { label: 'Failure code', value: r.failure_code ?? '—' },
        { label: 'Message', value: r.failure_message ?? '—' },
        { label: 'When', value: r.event_timestamp },
      ],
    }))
}

// 4. Quarantine: one warning item PER TENANT with open items ("N rows quarantined"). Now that the
// quarantine list row carries tenant_id (Chunk 1), we group the OPEN rows by tenant (attribution)
// instead of emitting a single unattributed open_count aggregate. For a TENANT token this is one
// item (its own open rows); for PLATFORM see-all it is one per tenant. `at` is null (a backlog has
// no single timestamp). The quarantine list is un-paginated, so per-tenant counts are complete.
export function deriveFromQuarantine(resp: QuarantineListResponse | undefined): AttentionItem[] {
  if (resp === undefined) return []
  const openByTenant = new Map<string, number>()
  // Chunk 9: capture the tenant_name alongside the count (all rows of a tenant share it).
  const nameByTenant = new Map<string, string | null>()
  for (const row of resp.items) {
    if (row.status !== 'open') continue
    openByTenant.set(row.tenant_id, (openByTenant.get(row.tenant_id) ?? 0) + 1)
    if (!nameByTenant.has(row.tenant_id)) nameByTenant.set(row.tenant_id, row.tenant_name ?? null)
  }
  return [...openByTenant.entries()].map(([tenantId, count]) => ({
    id: `quarantine:${tenantId}`,
    source: 'quarantine' as const,
    tenant_id: tenantId,
    tenant_name: nameByTenant.get(tenantId) ?? null, // Chunk 9
    severity: 'warning' as const,
    typeLabel: 'Quarantine backlog', // count-free (title carries the count) so type-filtering is stable
    title: `${count.toLocaleString()} row${count === 1 ? '' : 's'} quarantined`,
    context: 'Open validation failures',
    at: null,
    link: QUARANTINE_LINK,
    detail: [{ label: 'Open items', value: count.toLocaleString() }],
  }))
}

// Sort by DISPLAY severity (error→warning→info), then recency (newest first; null `at` last).
export function sortAttention(items: AttentionItem[]): AttentionItem[] {
  return [...items].sort((a, b) => {
    const bySev = SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity]
    if (bySev !== 0) return bySev
    if (a.at === b.at) return 0
    if (a.at === null) return 1
    if (b.at === null) return -1
    return b.at.localeCompare(a.at)
  })
}

// PLATFORM fleet attribution (Chunk 2-attribution): group the see-all items by owning tenant so
// Anjali sees WHICH tenant each item belongs to. Items are sorted within each group (severity then
// recency). A null tenant_id (audit system rows) forms its own group, rendered "System / platform"
// — NEVER folded into a real tenant. Groups are ordered by their most-severe item (error-first),
// then by tenant id for stability; the null-tenant (system) group sorts last on ties. The UI shows
// the tenant UUID (shortened + full in title/tooltip), not a friendly name (that is Chunk 9).
export type TenantGroup = { tenantId: string | null; items: AttentionItem[] }

// Sentinel key/value for the null-tenant (system) group — the grouping map key AND the
// tenant-FILTER value for "System / platform" (a real tenant_id is a UUID, never this).
const SYSTEM_KEY = SYSTEM_TENANT

export function groupByTenant(items: AttentionItem[]): TenantGroup[] {
  const byTenant = new Map<string, AttentionItem[]>()
  for (const item of items) {
    const key = item.tenant_id ?? SYSTEM_KEY
    const bucket = byTenant.get(key) ?? []
    bucket.push(item)
    byTenant.set(key, bucket)
  }
  const groups: TenantGroup[] = [...byTenant.entries()].map(([key, groupItems]) => ({
    tenantId: key === SYSTEM_KEY ? null : key,
    items: sortAttention(groupItems),
  }))
  return groups.sort((a, b) => {
    const rankA = Math.min(...a.items.map((i) => SEVERITY_RANK[i.severity]))
    const rankB = Math.min(...b.items.map((i) => SEVERITY_RANK[i.severity]))
    if (rankA !== rankB) return rankA - rankB
    if (a.tenantId === b.tenantId) return 0
    if (a.tenantId === null) return 1 // system group last on ties
    if (b.tenantId === null) return -1
    return a.tenantId.localeCompare(b.tenantId)
  })
}

// ── PLATFORM triage: client-side facets + filtering over the already-fetched items ──────────
// All facets are AUTO-POPULATED from the items actually present (no hardcoded tenant/type lists).
// Filtering is pure and client-side (no endpoint per filter).

export type AttentionFacets = {
  severities: AttentionSeverity[] // present severities, error→warning→info order
  types: string[] // distinct typeLabels present, alphabetical
  tenants: (string | null)[] // distinct tenant_ids present (null = system), sorted; null last
}

export function facetsOf(items: AttentionItem[]): AttentionFacets {
  const sevPresent = new Set(items.map((i) => i.severity))
  const severities = (['error', 'warning', 'info'] as AttentionSeverity[]).filter((s) => sevPresent.has(s))
  const types = [...new Set(items.map((i) => i.typeLabel))].sort((a, b) => a.localeCompare(b))
  const tenants = [...new Set(items.map((i) => i.tenant_id))].sort((a, b) =>
    a === null ? 1 : b === null ? -1 : a.localeCompare(b),
  )
  return { severities, types, tenants }
}

// Active filter set. null on any field = that dimension is unfiltered. `tenant` uses SYSTEM_TENANT
// for the null-tenant (system) group, else a real tenant_id. Filters combine with AND.
export type AttentionFilters = {
  severity: AttentionSeverity | null
  typeLabel: string | null
  tenant: string | null
}

export const NO_FILTERS: AttentionFilters = { severity: null, typeLabel: null, tenant: null }

export function hasActiveFilters(f: AttentionFilters): boolean {
  return f.severity !== null || f.typeLabel !== null || f.tenant !== null
}

export function applyFilters(items: AttentionItem[], f: AttentionFilters): AttentionItem[] {
  return items.filter((i) => {
    if (f.severity !== null && i.severity !== f.severity) return false
    if (f.typeLabel !== null && i.typeLabel !== f.typeLabel) return false
    if (f.tenant !== null) {
      const wanted = f.tenant === SYSTEM_TENANT ? null : f.tenant
      if (i.tenant_id !== wanted) return false
    }
    return true
  })
}
