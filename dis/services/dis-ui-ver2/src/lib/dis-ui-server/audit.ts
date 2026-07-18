import { useQuery } from '@tanstack/react-query'

import type { AuthSnapshot } from '../../auth/AuthSnapshot'
import { getJson } from './client'
import { isRealMode } from './mode'
import { QUARANTINE_TRACE_IDS } from './quarantine'

// Audit event log (tenant slice). Shaped EXACTLY to the real dis-ui-server contract
// (services/dis-ui-server/.../schemas/audit.py: AuditEventListResponse / AuditEventRow):
// GET /api/v1/audit, one tenant-scoped read over audit.events (RLS two-GUC, D91), bounded
// newest-100, list-only. Mode-aware: real mode calls the live endpoint; fixture mode
// (default + tests) returns plausible inlined rows so local dev needs no backend.
//
// PII: auth_principal / client_ip are omitted by the backend BY DESIGN; the "Who" column is
// the non-PII actor (service_name). A NAMED-actor display (real person names, as the mockup
// mocks) is pending the auth_principal exposure decision (docs/decisions.md) — never invented
// here. Filters window/outcome/trace_id are supported by the endpoint; wired as query params.
//
// This REPLACES the earlier fixture-only single-trace lookup (the dis-ui donor shape, not the
// mockup). A per-trace drill-in (GET /audit/{trace_id}) is a later slice (no route on main).

export type OutcomeWire = 'success' | 'failure' | 'skipped' | 'retried' | 'duplicate'
export type EventScopeWire = 'INGRESS_EVENT' | 'ROW'
export type WindowWire = '24h' | '7d' | '30d'

// One audit event row — field-for-field the wire shape (schemas/audit.py:AuditEventRow).
// auth_principal / client_ip are intentionally NOT here (PII, omitted server-side).
export type AuditEventRow = {
  id: string
  trace_id: string
  tenant_id: string | null // Chunk 1: owning tenant; null on PLATFORM see-all system rows
  tenant_name?: string | null // Chunk 9: identity_mirror.tenants.name; null for system rows / older backend
  prior_trace_id: string | null
  event_timestamp: string // ISO-8601, UTC as Z
  service_name: string // the non-PII actor
  stage: string // raw DB member (open vocabulary)
  event_scope: EventScopeWire
  outcome: OutcomeWire
  row_count: number | null
  rows_succeeded: number | null
  rows_failed: number | null
  duration_ms: number | null
  mapping_version: number | null // from mapping_version_id
  failure_code: string | null
  failure_message: string | null
  event_data: Record<string, unknown> | null
}

export type AuditEventListResponse = {
  items: AuditEventRow[]
}

// The endpoint's optional filters (window/outcome/trace_id). trace_id is carried for a future
// search box; the current surface wires window + outcome.
export type AuditFilters = {
  window?: WindowWire
  outcome?: OutcomeWire
  traceId?: string
}

// Plausible fixture shaped to AuditEventRow (newest first), grounded on the real seeded source
// / services. Numbers are illustrative, not fabricated truth: fixture mode is local-dev/test
// only; real mode reads the live endpoint. The quarantined row reuses the Quarantine screen's
// trace id (QUARANTINE_TRACE_IDS.acmeCanonical) so the two screens cross-reference.
const FIXTURE_EVENTS: AuditEventRow[] = [
  {
    id: '0190ac0e-1a01-7001-8a01-0000000000f1',
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000a1',
    trace_id: '0190ac0e-1a01-7001-8a01-000000000010',
    prior_trace_id: null,
    event_timestamp: '2026-06-09T09:12:04Z',
    service_name: 'streaming-consumer',
    stage: 'CANONICAL_WRITTEN',
    event_scope: 'INGRESS_EVENT',
    outcome: 'success',
    row_count: 1247,
    rows_succeeded: 1247,
    rows_failed: 0,
    duration_ms: 512,
    mapping_version: 1,
    failure_code: null,
    failure_message: null,
    event_data: { written_to_table: 'store_sku_current_position' },
  },
  {
    id: '0190ac0e-1a01-7001-8a01-0000000000f2',
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000a1',
    trace_id: '0190ac0e-1a01-7001-8a01-000000000010',
    prior_trace_id: null,
    event_timestamp: '2026-06-09T09:12:02Z',
    service_name: 'streaming-consumer',
    stage: 'POST_MAPPING_VALIDATED',
    event_scope: 'INGRESS_EVENT',
    outcome: 'success',
    row_count: 1247,
    rows_succeeded: 1247,
    rows_failed: 0,
    duration_ms: 88,
    mapping_version: 1,
    failure_code: null,
    failure_message: null,
    event_data: null,
  },
  {
    id: '0190ac0e-1a01-7001-8a01-0000000000f3',
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000b2',
    trace_id: '0190ac0e-1a01-7001-8a01-000000000010',
    prior_trace_id: null,
    event_timestamp: '2026-06-09T09:12:00Z',
    service_name: 'csv-ingest-worker',
    stage: 'BRONZE_WRITTEN',
    event_scope: 'INGRESS_EVENT',
    outcome: 'success',
    row_count: 1247,
    rows_succeeded: null,
    rows_failed: null,
    duration_ms: 140,
    mapping_version: null,
    failure_code: null,
    failure_message: null,
    event_data: { gcs_uri: 'gs://ithina-bronze-raw/tenant/…' },
  },
  {
    id: '0190ac0e-1a01-7001-8a01-0000000000f4',
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000b2',
    trace_id: QUARANTINE_TRACE_IDS.acmeCanonical,
    prior_trace_id: null,
    event_timestamp: '2026-06-08T16:40:03Z',
    service_name: 'streaming-consumer',
    stage: 'QUARANTINED',
    event_scope: 'ROW',
    outcome: 'success', // the disposition record itself lands (D78), not a pipeline failure
    row_count: null,
    rows_succeeded: null,
    rows_failed: 3,
    duration_ms: null,
    mapping_version: 1,
    failure_code: 'POST_VALIDATION_FAILED',
    failure_message: 'column price failed numeric cast',
    event_data: null,
  },
  {
    id: '0190ac0e-1a01-7001-8a01-0000000000f5',
    tenant_id: null,
    trace_id: '0190ac0e-1a01-7001-8a01-000000000021',
    prior_trace_id: null,
    event_timestamp: '2026-06-08T16:39:00Z',
    service_name: 'streaming-consumer',
    stage: 'MAPPING_EXECUTION',
    event_scope: 'INGRESS_EVENT',
    outcome: 'retried',
    row_count: null,
    rows_succeeded: null,
    rows_failed: null,
    duration_ms: 30,
    mapping_version: 1,
    failure_code: null,
    failure_message: null,
    event_data: null,
  },
  {
    id: '0190ac0e-1a01-7001-8a01-0000000000f6',
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000a1',
    trace_id: '0190ac0e-1a01-7001-8a01-000000000022',
    prior_trace_id: '0190ac0e-1a01-7001-8a01-000000000012',
    event_timestamp: '2026-06-08T12:00:00Z',
    service_name: 'csv-ingest-worker',
    stage: 'INGRESS_PUBLISHED',
    event_scope: 'INGRESS_EVENT',
    outcome: 'duplicate',
    row_count: 1247,
    rows_succeeded: null,
    rows_failed: null,
    duration_ms: null,
    mapping_version: null,
    failure_code: null,
    failure_message: null,
    event_data: { dedup: true },
  },
]

// Build the query string from the optional filters (mirrors quarantine-api's buildQuery).
function buildQuery(filters: AuditFilters): string {
  const params = new URLSearchParams()
  if (filters.window !== undefined) params.set('window', filters.window)
  if (filters.outcome !== undefined) params.set('outcome', filters.outcome)
  if (filters.traceId !== undefined && filters.traceId !== '') params.set('trace_id', filters.traceId)
  const qs = params.toString()
  return qs === '' ? '' : `?${qs}`
}

// Fixture-mode filtering: outcome and trace_id are applied deterministically. The `window`
// cutoff is a SERVER-SIDE concern (a relative-time filter over the live table); the inlined
// fixtures carry fixed historical dates, so fixture mode returns them regardless of `window`
// (applying a 24h cutoff to static fixtures would spuriously empty the list).
function applyFixtureFilters(rows: AuditEventRow[], filters: AuditFilters): AuditEventRow[] {
  return rows.filter((r) => {
    if (filters.outcome !== undefined && r.outcome !== filters.outcome) return false
    if (filters.traceId !== undefined && filters.traceId !== '' && r.trace_id !== filters.traceId) {
      return false
    }
    return true
  })
}

// GET /api/v1/audit. Tenant-scoped server-side (token tenant only; PLATFORM+ops sees the
// widened cross-tenant set from the same call). Real mode calls the live endpoint; fixture
// mode returns the inlined rows.
export async function getAuditEvents(filters: AuditFilters = {}): Promise<AuditEventListResponse> {
  if (isRealMode()) {
    return getJson<AuditEventListResponse>(`/api/v1/audit${buildQuery(filters)}`)
  }
  return { items: applyFixtureFilters(FIXTURE_EVENTS, filters) }
}

export function useAuditEvents(snapshot: AuthSnapshot | null, filters: AuditFilters = {}) {
  return useQuery({
    queryKey: [
      'dis-ui-server',
      'audit',
      'events',
      snapshot?.tenantId ?? 'none',
      filters.window ?? null,
      filters.outcome ?? null,
      filters.traceId ?? null,
    ],
    queryFn: () => getAuditEvents(filters),
    enabled: snapshot !== null,
    staleTime: Infinity,
    retry: false,
  })
}
