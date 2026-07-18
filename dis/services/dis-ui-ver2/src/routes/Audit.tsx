import { useEffect, useRef, useState } from 'react'

import { isOps } from '../auth/AuthSnapshot'
import { useAuth } from '../auth/useAuth'
import { ErrorState } from '../components/states/ErrorState'
import { LoadingState } from '../components/states/LoadingState'
import type { AuditEventRow, OutcomeWire, WindowWire } from '../lib/dis-ui-server/audit'
import { useAuditEvents } from '../lib/dis-ui-server/audit'
import { distinctTenants, matchesTenant, SYSTEM_TENANT, tenantFull, tenantName } from '../lib/dis-ui-server/tenant-label'

// Audit & Version History — mockup-faithful event-log table (audit.html): When · Who ·
// Action · Object · Detail. REAL (mode-aware): GET /api/v1/audit (AuditEventListResponse),
// tenant-scoped server-side (RLS two-GUC, D91), bounded newest-100. Filters window/outcome
// are wired to the real query params. The old single-trace lookup (dis-ui donor shape, not the
// mockup) is replaced; a per-trace drill-in (GET /audit/{trace_id}) is a later slice.
//
// "Who" = service_name (the non-PII actor). auth_principal is omitted by the backend by
// design; a NAMED-actor display (real person names, as the mockup mocks) is pending the
// auth_principal exposure decision (docs/decisions.md). We show the service, never invent names.

const OUTCOME_BADGE: Record<OutcomeWire, string> = {
  success: 'b-ok',
  failure: 'b-fail',
  retried: 'b-warn',
  skipped: 'b-mut',
  duplicate: 'b-info',
}

const WINDOWS: WindowWire[] = ['24h', '7d', '30d']
const OUTCOMES: OutcomeWire[] = ['success', 'failure', 'retried', 'skipped', 'duplicate']

// When: readable local time with the full ISO carried on the cell's title (mockup: hover any
// timestamp for the full value).
function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// Object: the thing acted on — the mapping version when present, else the event scope.
function objectOf(r: AuditEventRow): string {
  if (r.mapping_version !== null) return `mapping v${r.mapping_version}`
  return r.event_scope === 'ROW' ? 'row' : 'ingress event'
}

// Detail: failure text when present; else a compact rows summary; else an event_data key hint.
function detailOf(r: AuditEventRow): string {
  if (r.failure_message !== null) return r.failure_message
  if (r.failure_code !== null) return r.failure_code
  if (r.row_count !== null) {
    const failed = r.rows_failed ?? 0
    return failed > 0 ? `${r.row_count} rows · ${failed} failed` : `${r.row_count} rows`
  }
  if (r.event_data !== null && Object.keys(r.event_data).length > 0) {
    return Object.keys(r.event_data).join(', ')
  }
  return '—'
}

// Any nullable scalar -> its string, or an honest "—".
function orDash(value: string | number | null): string {
  return value === null ? '—' : String(value)
}

// Render an event_data value WITHOUT assuming a shape: strings pass through; anything else
// (number/bool/object/array) is JSON-stringified. event_data is an arbitrary jsonb bag.
function eventDataValue(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value)
}

// Row-click detail drawer — the servable audit event (Item 4b). Trace lineage + actor + stage/
// outcome + the three counts + duration + mapping version + failure, and event_data rendered as
// honest key/value pairs (no assumed shape). Scoped to AUDIT only (no mapping "version history",
// which is a separate fixture-only concern). Reads the in-hand row (no extra fetch). Esc + scrim
// close; the panel takes focus and carries dialog aria.
function AuditDetail({ event, onClose }: { event: AuditEventRow | null; onClose: () => void }) {
  const open = event !== null
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    panelRef.current?.focus()
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const r = event
  const eventDataEntries = r !== null && r.event_data !== null ? Object.entries(r.event_data) : []
  return (
    <>
      <div className={open ? 'drawer-scrim on' : 'drawer-scrim'} onClick={onClose} />
      <div
        className={open ? 'drawer on' : 'drawer'}
        role="dialog"
        aria-modal="true"
        aria-hidden={!open}
        aria-label="Audit event detail"
        tabIndex={-1}
        ref={panelRef}
      >
        {r !== null ? (
          <>
            <div className="dhd">
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9, flexWrap: 'wrap' }}>
                  <h3>{r.stage}</h3>
                  <span className={`badge ${OUTCOME_BADGE[r.outcome]}`}>{r.outcome}</span>
                </div>
                <div className="sub" style={{ marginTop: 3 }}>
                  {r.service_name} · {formatWhen(r.event_timestamp)}
                </div>
              </div>
              <button className="iconbtn" onClick={onClose} aria-label="Close detail">
                ×
              </button>
            </div>

            <div className="dbd">
              <div className="detsec">
                <h4>Event</h4>
                <dl className="kv">
                  <dt>Actor</dt>
                  <dd>{r.service_name}</dd>
                  <dt>Stage</dt>
                  <dd>{r.stage}</dd>
                  <dt>Scope</dt>
                  <dd>{r.event_scope}</dd>
                  <dt>Outcome</dt>
                  <dd>
                    <span className={`badge ${OUTCOME_BADGE[r.outcome]}`}>{r.outcome}</span>
                  </dd>
                  <dt>Mapping version</dt>
                  <dd className="mono">{r.mapping_version !== null ? `v${r.mapping_version}` : '—'}</dd>
                </dl>
              </div>

              <div className="detsec">
                <h4>Rows</h4>
                <dl className="kv">
                  <dt>Row count</dt>
                  <dd className="mono">{orDash(r.row_count)}</dd>
                  <dt>Succeeded</dt>
                  <dd className="mono">{orDash(r.rows_succeeded)}</dd>
                  <dt>Failed</dt>
                  <dd className="mono">{orDash(r.rows_failed)}</dd>
                  <dt>Duration</dt>
                  <dd className="mono">{r.duration_ms !== null ? `${r.duration_ms} ms` : '—'}</dd>
                </dl>
              </div>

              {r.failure_code !== null || r.failure_message !== null ? (
                <div className="detsec">
                  <h4>Failure</h4>
                  <div className="failbox" role="note">
                    <b>{r.failure_code ?? 'error'}</b>
                    {r.failure_message !== null ? <div className="mono" style={{ marginTop: 6 }}>{r.failure_message}</div> : null}
                  </div>
                </div>
              ) : null}

              <div className="detsec">
                <h4>Trace &amp; refs</h4>
                <dl className="kv">
                  <dt>Trace id</dt>
                  <dd className="mono">{r.trace_id}</dd>
                  <dt>Prior trace</dt>
                  <dd className="mono">{r.prior_trace_id ?? '—'}</dd>
                  <dt>Event id</dt>
                  <dd className="mono">{r.id}</dd>
                </dl>
              </div>

              {/* event_data is an arbitrary jsonb bag — rendered as key/values, shape not assumed. */}
              <div className="detsec">
                <h4>Event data</h4>
                {eventDataEntries.length === 0 ? (
                  <div className="mut">—</div>
                ) : (
                  <dl className="kv">
                    {eventDataEntries.map(([k, v]) => (
                      <div key={k} style={{ display: 'contents' }}>
                        <dt className="mono">{k}</dt>
                        <dd className="mono">{eventDataValue(v)}</dd>
                      </div>
                    ))}
                  </dl>
                )}
              </div>
            </div>
          </>
        ) : null}
      </div>
    </>
  )
}

export function Audit() {
  const { snapshot } = useAuth()
  const ops = snapshot !== null && isOps(snapshot)
  const [selected, setSelected] = useState<AuditEventRow | null>(null)
  const [window, setWindow] = useState<WindowWire | null>(null)
  const [outcome, setOutcome] = useState<OutcomeWire | null>(null)
  const [tenantFilter, setTenantFilter] = useState<string | null>(null) // PLATFORM only

  const q = useAuditEvents(snapshot, {
    window: window ?? undefined,
    outcome: outcome ?? undefined,
  })
  const rows = q.data?.items ?? []
  const tenantOptions = ops ? distinctTenants(rows.map((r) => r.tenant_id)) : []
  const displayRows = ops ? rows.filter((r) => matchesTenant(r.tenant_id, tenantFilter)) : rows
  // Chunk 9-FE: tenant_id → name map for labelling the filter options by name (value stays tenant_id).
  const tenantNames = new Map(rows.map((r) => [r.tenant_id, r.tenant_name ?? null]))

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Audit &amp; Version History</h1>
        </div>
      </div>

      {/* Filters wired to the real query params (window, outcome). Search-by-user and Export
          from the mockup are omitted (no backend text-search / export route on main). */}
      <div className="toolbar">
        <div className="segment" role="group" aria-label="Time window">
          <button type="button" className={window === null ? 'on' : ''} onClick={() => setWindow(null)}>
            All time
          </button>
          {WINDOWS.map((w) => (
            <button key={w} type="button" className={window === w ? 'on' : ''} onClick={() => setWindow(w)}>
              {w}
            </button>
          ))}
        </div>
        <label className="filter">
          Outcome{' '}
          <select
            aria-label="Outcome"
            value={outcome ?? ''}
            onChange={(e) => setOutcome(e.target.value === '' ? null : (e.target.value as OutcomeWire))}
          >
            <option value="">All</option>
            {OUTCOMES.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </label>
        {ops ? (
          <label className="filter">
            Tenant{' '}
            <select
              aria-label="Tenant"
              value={tenantFilter ?? ''}
              onChange={(e) => setTenantFilter(e.target.value === '' ? null : e.target.value)}
            >
              <option value="">All</option>
              {tenantOptions.map((t) => {
                const value = t ?? SYSTEM_TENANT
                return (
                  <option key={value} value={value} title={tenantFull(t)}>
                    {tenantName(tenantNames.get(t) ?? null, t)}
                  </option>
                )
              })}
            </select>
          </label>
        ) : null}
      </div>

      <div className="card">
        <div className="hd">
          <h3>Audit &amp; version history</h3>
          <span className="badge b-mut">{displayRows.length}</span>
        </div>
        {q.isPending ? (
          <LoadingState label="Loading audit events…" />
        ) : q.isError ? (
          <ErrorState message="Could not load audit events." />
        ) : displayRows.length === 0 ? (
          <div className="bd">
            <div className="empty">
              <h4>No audit events</h4>
              <div>No pipeline events match the current filters.</div>
            </div>
          </div>
        ) : (
          <div style={{ overflow: 'auto' }}>
            <table className="tbl">
              <thead>
                <tr>
                  {ops ? <th>Tenant</th> : null}
                  <th>When</th>
                  <th>Who</th>
                  <th>Action</th>
                  <th>Object</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {displayRows.map((r) => (
                  <tr
                    key={r.id}
                    className="click"
                    tabIndex={0}
                    onClick={() => setSelected(r)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setSelected(r)
                      }
                    }}
                  >
                    {ops ? (
                      <td className="id" title={tenantFull(r.tenant_id)}>
                        {tenantName(r.tenant_name, r.tenant_id)}
                      </td>
                    ) : null}
                    <td className="id" title={r.event_timestamp}>
                      {formatWhen(r.event_timestamp)}
                    </td>
                    {/* Who = the non-PII actor (service_name); named actor pending auth_principal. */}
                    <td className="pri-name">{r.service_name}</td>
                    {/* Action = stage, coloured by outcome (encodes stage + outcome). */}
                    <td>
                      <span className={`badge ${OUTCOME_BADGE[r.outcome]}`}>{r.stage}</span>
                    </td>
                    <td className="id">{objectOf(r)}</td>
                    <td
                      className={r.failure_message !== null ? 'mono' : 'id'}
                      style={r.failure_message !== null ? { color: 'var(--fail)' } : undefined}
                    >
                      {detailOf(r)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <AuditDetail event={selected} onClose={() => setSelected(null)} />
    </>
  )
}
