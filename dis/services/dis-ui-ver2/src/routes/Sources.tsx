import { useEffect, useRef, useState } from 'react'

import { isOps } from '../auth/AuthSnapshot'
import { useAuth } from '../auth/useAuth'
import { ErrorState } from '../components/states/ErrorState'
import { LoadingState } from '../components/states/LoadingState'
import type { ChannelWire, SourceRow, SourceStatus } from '../lib/dis-ui-server/sources'
import { useSources } from '../lib/dis-ui-server/sources'
import { distinctTenants, matchesTenant, SYSTEM_TENANT, tenantFull, tenantName } from '../lib/dis-ui-server/tenant-label'

// Data Pipelines — the source registry, wired to the real GET /api/v1/sources (Phase B, D112).
// REAL columns from the registry: Source (display_name + source_id), Method (channel), Schedule,
// Status (operator enablement). The runtime columns the mockup also shows (Last/Next run,
// Quality %, connector health) are L1 — worker-produced telemetry with no registry/route yet —
// shown as a marked-pending note, NOT fabricated. channel NULL (un-inferred by the backfill)
// renders "—". A row click opens a detail drawer of the REGISTRY facts only (no liveness).

const STATUS_BADGE: Record<SourceStatus, string> = {
  active: 'b-ok',
  paused: 'b-warn',
  disabled: 'b-mut',
}
const STATUS_DOT: Record<SourceStatus, string> = {
  active: 'd-ok',
  paused: 'd-warn',
  disabled: 'd-mut',
}

// Presentational label for the real dis_channel enum (a display of the actual value).
const METHOD_LABEL: Record<ChannelWire, string> = {
  csv_upload: 'Manual CSV',
  api: 'API',
  csv_erp: 'ERP CSV',
  reverse_api: 'Reverse API',
}

function methodLabel(channel: ChannelWire | null): string {
  return channel === null ? '—' : METHOD_LABEL[channel]
}

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function StatusBadge({ status }: { status: SourceStatus }) {
  return (
    <span className={`badge ${STATUS_BADGE[status]}`}>
      <span className={`dot ${STATUS_DOT[status]}`} />
      {status}
    </span>
  )
}

// Row-click detail drawer — REGISTRY facts only (Item 4a honesty guard): identity + config +
// enablement + the registry record timestamps. Deliberately shows NO liveness/last-ingest/health;
// that is the Connector Health surface's job (D116). Reads the in-hand row (no extra fetch). Esc +
// scrim close; the panel takes focus and carries dialog aria.
function SourceDetail({ source, onClose }: { source: SourceRow | null; onClose: () => void }) {
  const open = source !== null
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

  const s = source
  return (
    <>
      <div className={open ? 'drawer-scrim on' : 'drawer-scrim'} onClick={onClose} />
      <div
        className={open ? 'drawer on' : 'drawer'}
        role="dialog"
        aria-modal="true"
        aria-hidden={!open}
        aria-label="Data source detail"
        tabIndex={-1}
        ref={panelRef}
      >
        {s !== null ? (
          <>
            <div className="dhd">
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9, flexWrap: 'wrap' }}>
                  <h3>{s.display_name}</h3>
                  <StatusBadge status={s.status} />
                </div>
                <div className="sub" style={{ marginTop: 3 }}>
                  <span className="id">{s.source_id}</span> · {methodLabel(s.channel)}
                </div>
              </div>
              <button className="iconbtn" onClick={onClose} aria-label="Close detail">
                ×
              </button>
            </div>

            <div className="dbd">
              <div className="detsec">
                <h4>Registry</h4>
                <dl className="kv">
                  <dt>Source ID</dt>
                  <dd className="mono">{s.source_id}</dd>
                  <dt>Display name</dt>
                  <dd>{s.display_name}</dd>
                  <dt>Method</dt>
                  <dd>{methodLabel(s.channel)}</dd>
                  <dt>Store</dt>
                  <dd className="mono">{s.store_id ?? '—'}</dd>
                  <dt>Schedule</dt>
                  <dd>{s.schedule ?? '—'}</dd>
                  <dt>Status</dt>
                  <dd>
                    <StatusBadge status={s.status} />
                  </dd>
                  <dt>Registered</dt>
                  <dd className="mono">{formatWhen(s.created_at)}</dd>
                  <dt>Registry updated</dt>
                  <dd className="mono">{formatWhen(s.updated_at)}</dd>
                </dl>
              </div>
              {/* Honesty guard: this drawer is registry configuration only. */}
              <div className="note" role="note">
                Registry configuration only. Runtime health, last ingest, and freshness live on
                Connector Health — not shown here.
              </div>
            </div>
          </>
        ) : null}
      </div>
    </>
  )
}

export function Sources() {
  const { snapshot } = useAuth()
  const ops = snapshot !== null && isOps(snapshot)
  const q = useSources(snapshot)
  const rows = q.data ?? []
  const [selected, setSelected] = useState<SourceRow | null>(null)
  const [tenantFilter, setTenantFilter] = useState<string | null>(null) // PLATFORM only
  const tenantOptions = ops ? distinctTenants(rows.map((s) => s.tenant_id)) : []
  const displayRows = ops ? rows.filter((s) => matchesTenant(s.tenant_id, tenantFilter)) : rows
  // Chunk 9-FE: tenant_id → name map for labelling the filter options by name (value stays tenant_id).
  const tenantNames = new Map<string | null, string | null>(rows.map((s) => [s.tenant_id, s.tenant_name ?? null]))

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Data Sources</h1>
        </div>
      </div>

      {/* PLATFORM only: tenant filter (Sources has no domain filters of its own). */}
      {ops ? (
        <div className="toolbar">
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
        </div>
      ) : null}

      {q.isPending ? (
        <LoadingState label="Loading data sources…" />
      ) : q.isError ? (
        <ErrorState message="Could not load data sources." />
      ) : displayRows.length === 0 ? (
        <div className="empty">
          <h4>No data sources</h4>
          <div>No sources registered yet. Connect a data source to add one.</div>
        </div>
      ) : (
        <div className="card">
          <div className="hd">
            <h3>Sources</h3>
            <span className="badge b-mut">{displayRows.length}</span>
          </div>
          <div style={{ overflow: 'auto' }}>
            <table className="tbl">
              <thead>
                <tr>
                  {ops ? <th>Tenant</th> : null}
                  <th>Source</th>
                  <th>Method</th>
                  <th>Schedule</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {displayRows.map((s) => (
                  <tr
                    key={s.source_id}
                    className="click"
                    tabIndex={0}
                    onClick={() => setSelected(s)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setSelected(s)
                      }
                    }}
                  >
                    {ops ? (
                      <td className="id" title={tenantFull(s.tenant_id)}>
                        {tenantName(s.tenant_name, s.tenant_id)}
                      </td>
                    ) : null}
                    <td>
                      <span className="pri-name">{s.display_name}</span>
                      <div className="id">{s.source_id}</div>
                    </td>
                    {/* Method = the real channel; NULL (un-inferred) -> "—". */}
                    <td className="id">{methodLabel(s.channel)}</td>
                    <td className="id">{s.schedule ?? '—'}</td>
                    <td>
                      <span className={`badge ${STATUS_BADGE[s.status]}`}>{s.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <SourceDetail source={selected} onClose={() => setSelected(null)} />
    </>
  )
}
