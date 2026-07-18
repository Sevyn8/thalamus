import { describe, expect, it } from 'vitest'

import type { AuditEventRow } from './audit'
import type { ConnectorHealthRow } from './connector-health'
import type { QuarantineListResponse, QuarantineListRow } from './quarantine-api'
import type { RunRow } from './runs'
import {
  deriveFromAudit,
  deriveFromConnectors,
  deriveFromQuarantine,
  deriveFromRuns,
  groupByTenant,
  sortAttention,
} from './needs-attention'

const TA = '0190ac10-1a01-7001-8a01-0000000000a1'
const TB = '0190ac10-1a01-7001-8a01-0000000000b2'

function run(over: Partial<RunRow>): RunRow {
  return {
    id: 'r1',
    trace_id: 't1',
    tenant_id: TA,
    store_id: null,
    store_name: null,
    source_id: 'manual_csv_upload',
    source_name: 'Manual CSV Upload',
    template_id: null,
    template_name: null,
    method: 'csv_upload',
    status: 'succeeded',
    mapping_version: null,
    seen_before: false,
    source_payload_id: null,
    file_name: null,
    input_row_count: 100,
    accepted: 100,
    quarantined: null,
    received_at: '2026-06-03T09:00:00Z',
    published_at: null,
    completed_at: null,
    ...over,
  }
}

function connector(over: Partial<ConnectorHealthRow>): ConnectorHealthRow {
  return {
    tenant_id: TA,
    source_id: 'c1',
    display_name: 'Square POS',
    channel: 'api',
    heartbeat_label: null,
    status: 'healthy',
    last_seen_at: '2026-06-03T08:00:00Z',
    last_error_at: null,
    last_error_detail: null,
    auth_expires_at: null,
    rate_limit_state: null,
    missed_intervals: null,
    ...over,
  }
}

function auditRow(over: Partial<AuditEventRow>): AuditEventRow {
  return {
    id: 'a1',
    trace_id: 'trace-abcdef12',
    tenant_id: TA,
    prior_trace_id: null,
    event_timestamp: '2026-06-03T09:08:00Z',
    service_name: 'streaming-consumer',
    stage: 'CANONICAL_WRITTEN',
    event_scope: 'INGRESS_EVENT',
    outcome: 'success',
    row_count: null,
    rows_succeeded: null,
    rows_failed: null,
    duration_ms: null,
    mapping_version: null,
    failure_code: null,
    failure_message: null,
    event_data: null,
    ...over,
  }
}

function qRow(over: Partial<QuarantineListRow>): QuarantineListRow {
  return {
    id: 'row:q1',
    kind: 'row',
    tenant_id: TA,
    trace_id: 'qt1',
    source_id: 'manual_csv_upload',
    source: 'Manual CSV Upload',
    store_id: null,
    store_name: null,
    error_reason: 'SCHEMA_INVALID',
    failure_stage: 'canonical-shape',
    failed_at: '2026-06-03T09:00:00Z',
    status: 'open',
    ...over,
  }
}

function qResp(items: QuarantineListRow[]): QuarantineListResponse {
  return { items, open_count: items.filter((r) => r.status === 'open').length }
}

describe('deriveFromRuns', () => {
  it('failed verdict → one error item carrying the run tenant_id', () => {
    const items = deriveFromRuns([run({ id: 'x', status: 'failed', tenant_id: TB })])
    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({ source: 'runs', severity: 'error', title: 'Run failed', tenant_id: TB })
    expect(items[0].link.to).toBe('/ingestion-runs')
  })

  it('quarantined verdict → warning item', () => {
    const items = deriveFromRuns([run({ status: 'quarantined' })])
    expect(items[0]).toMatchObject({ severity: 'warning', title: 'Run quarantined' })
  })

  it('accepted < input (partial) on a non-terminal verdict → warning item', () => {
    const items = deriveFromRuns([run({ status: 'succeeded', accepted: 997, input_row_count: 1000 })])
    expect(items[0]).toMatchObject({ severity: 'warning', title: 'Run partially accepted' })
  })

  it('clean succeeded run (accepted == input) → no item', () => {
    expect(deriveFromRuns([run({ status: 'succeeded', accepted: 100, input_row_count: 100 })])).toEqual([])
  })

  it('one item per run (failed takes precedence, not doubled)', () => {
    const items = deriveFromRuns([run({ id: 'x', status: 'failed', accepted: 1, input_row_count: 9 })])
    expect(items).toHaveLength(1)
    expect(items[0].title).toBe('Run failed')
  })
})

describe('deriveFromConnectors', () => {
  it('stale/pending → warning; auth_expiring → warning; rate_limited → info; healthy → none', () => {
    expect(deriveFromConnectors([connector({ status: 'stale' })])[0]).toMatchObject({ severity: 'warning', title: 'Connector stale' })
    expect(deriveFromConnectors([connector({ status: 'pending' })])[0]).toMatchObject({ severity: 'warning', title: 'Connector pending' })
    expect(deriveFromConnectors([connector({ status: 'auth_expiring' })])[0]).toMatchObject({ severity: 'warning', title: 'Auth expiring' })
    expect(deriveFromConnectors([connector({ status: 'rate_limited' })])[0]).toMatchObject({ severity: 'info', title: 'Rate-limited' })
    expect(deriveFromConnectors([connector({ status: 'healthy' })])).toEqual([])
  })
  it('carries the connector tenant_id and deep-links to connector health', () => {
    const item = deriveFromConnectors([connector({ status: 'stale', tenant_id: TB })])[0]
    expect(item.tenant_id).toBe(TB)
    expect(item.link.to).toBe('/connector-health')
  })
})

describe('deriveFromAudit', () => {
  it('failure rows → error items; non-failure ignored; tenant_id passed through', () => {
    const items = deriveFromAudit([
      auditRow({ id: 'ok', outcome: 'success' }),
      auditRow({ id: 'bad', outcome: 'failure', tenant_id: TB, failure_code: 'CANONICAL_SHAPE_INVALID', failure_message: 'nope' }),
    ])
    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({ source: 'audit', severity: 'error', title: 'Ingestion failure', tenant_id: TB })
    expect(items[0].link.to).toBe('/audit')
  })

  it('null-tenant (system) failure row → item with tenant_id null (not fabricated)', () => {
    const items = deriveFromAudit([auditRow({ id: 'sys', outcome: 'failure', tenant_id: null })])
    expect(items[0].tenant_id).toBeNull()
  })
})

describe('deriveFromQuarantine', () => {
  it('groups OPEN rows by tenant → one attributed item per tenant', () => {
    const items = deriveFromQuarantine(
      qResp([
        qRow({ id: 'row:1', tenant_id: TA }),
        qRow({ id: 'row:2', tenant_id: TA }),
        qRow({ id: 'row:3', tenant_id: TB }),
      ]),
    )
    const byTenant = Object.fromEntries(items.map((i) => [i.tenant_id, i]))
    expect(items).toHaveLength(2)
    expect(byTenant[TA]).toMatchObject({ source: 'quarantine', severity: 'warning', title: '2 rows quarantined' })
    expect(byTenant[TB]).toMatchObject({ title: '1 row quarantined' })
    expect(byTenant[TA].link.to).toBe('/data-quality')
  })

  it('ignores resolved rows; empty/undefined → none', () => {
    expect(deriveFromQuarantine(qResp([qRow({ status: 'resolved' })]))).toEqual([])
    expect(deriveFromQuarantine({ items: [], open_count: 0 })).toEqual([])
    expect(deriveFromQuarantine(undefined)).toEqual([])
  })
})

describe('sortAttention', () => {
  it('orders by severity (error→warning→info) then recency (newest first)', () => {
    const items = sortAttention([
      ...deriveFromConnectors([connector({ status: 'rate_limited' })]), // info
      ...deriveFromRuns([run({ id: 'old', status: 'failed', received_at: '2026-06-01T00:00:00Z' })]), // error, older
      ...deriveFromRuns([run({ id: 'new', status: 'failed', received_at: '2026-06-05T00:00:00Z' })]), // error, newer
      ...deriveFromQuarantine(qResp([qRow({})])), // warning
    ])
    expect(items.map((i) => i.severity)).toEqual(['error', 'error', 'warning', 'info'])
    // within error, newer first
    expect(items[0].id).toBe('run:new')
    expect(items[1].id).toBe('run:old')
  })
})

describe('groupByTenant (PLATFORM attribution)', () => {
  it('groups items by tenant_id; a null tenant_id forms its own (system) group, not folded into a tenant', () => {
    const items = [
      ...deriveFromRuns([run({ id: 'a', status: 'failed', tenant_id: TA })]),
      ...deriveFromConnectors([connector({ status: 'stale', tenant_id: TB })]),
      ...deriveFromAudit([auditRow({ id: 'sys', outcome: 'failure', tenant_id: null })]),
    ]
    const groups = groupByTenant(items)
    const ids = groups.map((g) => g.tenantId)
    expect(new Set(ids)).toEqual(new Set([TA, TB, null]))
    // the null-tenant group carries the system audit item, never a fabricated tenant
    const system = groups.find((g) => g.tenantId === null)
    expect(system?.items).toHaveLength(1)
    expect(system?.items[0].source).toBe('audit')
    // each real tenant group carries only its own items
    expect(groups.find((g) => g.tenantId === TA)?.items.every((i) => i.tenant_id === TA)).toBe(true)
    expect(groups.find((g) => g.tenantId === TB)?.items.every((i) => i.tenant_id === TB)).toBe(true)
  })

  it('orders groups by their most-severe item (error-first); system group last on ties', () => {
    const items = [
      ...deriveFromConnectors([connector({ status: 'rate_limited', tenant_id: TB })]), // info
      ...deriveFromRuns([run({ id: 'e', status: 'failed', tenant_id: TA })]), // error
    ]
    const groups = groupByTenant(items)
    expect(groups[0].tenantId).toBe(TA) // the tenant with an error sorts first
    expect(groups[1].tenantId).toBe(TB)
  })
})

describe('facetsOf + applyFilters (PLATFORM triage, client-side)', () => {
  // A mixed fleet: tenant A has a failed run (error) + stale connector (warning); tenant B has a
  // quarantine backlog (warning); a null-tenant (system) audit failure (error).
  const items = [
    ...deriveFromRuns([run({ id: 'a1', status: 'failed', tenant_id: TA })]),
    ...deriveFromConnectors([connector({ status: 'stale', tenant_id: TA })]),
    ...deriveFromQuarantine(qResp([qRow({ id: 'row:b', tenant_id: TB })])),
    ...deriveFromAudit([auditRow({ id: 'sys', outcome: 'failure', tenant_id: null })]),
  ]

  it('facetsOf auto-populates severities (present, ordered), types (sorted), tenants (null last)', async () => {
    const { facetsOf } = await import('./needs-attention')
    const f = facetsOf(items)
    expect(f.severities).toEqual(['error', 'warning']) // no 'info' present; order preserved
    expect(f.types).toEqual([...f.types].sort()) // alphabetical
    expect(f.types).toContain('Run failed')
    expect(f.types).toContain('Quarantine backlog')
    expect(f.tenants).toEqual([TA, TB, null]) // sorted, null (system) last
  })

  it('applyFilters: severity narrows', async () => {
    const { applyFilters, NO_FILTERS } = await import('./needs-attention')
    const errors = applyFilters(items, { ...NO_FILTERS, severity: 'error' })
    expect(errors.every((i) => i.severity === 'error')).toBe(true)
    expect(errors.length).toBe(2) // failed run + system audit failure
  })

  it('applyFilters: type narrows', async () => {
    const { applyFilters, NO_FILTERS } = await import('./needs-attention')
    const res = applyFilters(items, { ...NO_FILTERS, typeLabel: 'Quarantine backlog' })
    expect(res).toHaveLength(1)
    expect(res[0].source).toBe('quarantine')
  })

  it('applyFilters: tenant narrows (incl. SYSTEM_TENANT for the null group)', async () => {
    const { applyFilters, NO_FILTERS, SYSTEM_TENANT } = await import('./needs-attention')
    expect(applyFilters(items, { ...NO_FILTERS, tenant: TA }).every((i) => i.tenant_id === TA)).toBe(true)
    const sys = applyFilters(items, { ...NO_FILTERS, tenant: SYSTEM_TENANT })
    expect(sys).toHaveLength(1)
    expect(sys[0].tenant_id).toBeNull()
  })

  it('applyFilters: filters combine AND; NO_FILTERS returns everything', async () => {
    const { applyFilters, NO_FILTERS } = await import('./needs-attention')
    expect(applyFilters(items, NO_FILTERS)).toHaveLength(items.length)
    // error AND tenant A → only the failed run (the system error is tenant null, excluded)
    const res = applyFilters(items, { severity: 'error', typeLabel: null, tenant: TA })
    expect(res).toHaveLength(1)
    expect(res[0].id).toBe('run:a1')
  })

  it('hasActiveFilters reflects any set dimension', async () => {
    const { hasActiveFilters, NO_FILTERS } = await import('./needs-attention')
    expect(hasActiveFilters(NO_FILTERS)).toBe(false)
    expect(hasActiveFilters({ ...NO_FILTERS, severity: 'error' })).toBe(true)
  })
})
