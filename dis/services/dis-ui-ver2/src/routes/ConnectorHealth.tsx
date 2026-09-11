import { useState } from 'react'

import { isOps } from '../auth/AuthSnapshot'
import { useAuth } from '../auth/useAuth'
import { ErrorState } from '../components/states/ErrorState'
import { LoadingState } from '../components/states/LoadingState'
import { StatusBadge } from '../components/StatusBadge'
import type { StatusTone } from '../components/StatusBadge'
import type {
  ChannelWire,
  ConnectorHealthRow,
  StatusWire,
} from '../lib/dis-ui-server/connector-health'
import { useConnectorHealth } from '../lib/dis-ui-server/connector-health'
import { distinctTenants, matchesTenant, SYSTEM_TENANT, tenantFull, tenantName } from '../lib/dis-ui-server/tenant-label'

// Connector Health (connector-health.html): a card grid (g3), one card per connector — status
// dot + name + method chip, a status badge, and a 5-field kv (Last seen, Heartbeat, Missed
// intervals, Auth expiry, Rate limit). Wired to GET /api/v1/connector-health via
// the connector-health.ts client. Toolbar: Status + Method filters (client-side over the list) and
// KPI badges (stale / attention / healthy).
//
// HONEST RENDERING (the core discipline — the mockup's numbers are ILLUSTRATIVE): every field
// shows ONLY what the wire carries. Today the sole producer is csv-ingest-worker (CSV), so
// CSV connectors have a real last_seen_at + status but null auth/rate/missed → "—"; the deferred
// receivers come back status='pending' with every field null. We NEVER render the mockup's
// "in 42 days" / "698/700" / "1 missed" — those are null until a producer emits them.

// status → the badge tone (StatusBadge maps tone → .b-*), the dot class, and the label.
const STATUS_META: Record<StatusWire, { tone: StatusTone; dot: string; label: string }> = {
  healthy: { tone: 'success', dot: 'd-ok', label: 'Healthy' },
  stale: { tone: 'danger', dot: 'd-fail', label: 'Stale - escalated' },
  auth_expiring: { tone: 'warning', dot: 'd-warn', label: 'Auth expiring' },
  rate_limited: { tone: 'warning', dot: 'd-warn', label: 'Rate limited' },
  pending: { tone: 'neutral', dot: 'd-mut', label: 'Receiver pending' },
}

// channel → the method chip label + its dot colour (mockup palette). null → "—".
const METHOD_META: Record<ChannelWire, { label: string; color: string }> = {
  csv_upload: { label: 'Manual CSV', color: '#5ac8b0' },
  api: { label: 'API pull', color: 'var(--ion)' },
  reverse_api: { label: 'Reverse API', color: 'var(--cyan)' },
  csv_erp: { label: 'ERP CSV', color: '#8b7cf6' },
}

const STATUSES: StatusWire[] = ['healthy', 'stale', 'auth_expiring', 'rate_limited', 'pending']
const CHANNELS: ChannelWire[] = ['csv_upload', 'api', 'reverse_api', 'csv_erp']

const DASH = '—' // the honest "not emitted" placeholder

// Relative "time ago" from an ISO instant; null → "—". Coarse buckets (the wire has no sub-second).
function ago(iso: string | null): string {
  if (iso === null) return DASH
  const ms = Date.now() - new Date(iso).getTime()
  if (!Number.isFinite(ms)) return DASH
  if (ms < 0) return 'just now'
  if (ms < 60_000) return `${Math.round(ms / 1000)}s ago`
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)}m ago`
  if (ms < 86_400_000) return `${Math.round(ms / 3_600_000)}h ago`
  return `${Math.round(ms / 86_400_000)}d ago`
}

// Relative "in N" from a future ISO instant (auth expiry); null → "—".
function until(iso: string | null): string {
  if (iso === null) return DASH
  const ms = new Date(iso).getTime() - Date.now()
  if (!Number.isFinite(ms)) return DASH
  if (ms <= 0) return 'expired'
  if (ms < 3_600_000) return `in ${Math.round(ms / 60_000)}m`
  if (ms < 86_400_000) return `in ${Math.round(ms / 3_600_000)}h`
  return `in ${Math.round(ms / 86_400_000)} days`
}

function methodChip(channel: ChannelWire | null) {
  if (channel === null) return <span className="method">{DASH}</span>
  const { label, color } = METHOD_META[channel]
  return (
    <span className="method">
      <span className="g" style={{ background: color }} />
      {label}
    </span>
  )
}

function ConnectorCard({ c, showTenant }: { c: ConnectorHealthRow; showTenant: boolean }) {
  const meta = STATUS_META[c.status]
  return (
    <div className="card">
      <div className="bd">
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <span className={`dot ${meta.dot}`} />
          <b style={{ flex: 1 }}>{c.display_name}</b>
          {methodChip(c.channel)}
        </div>
        <div style={{ margin: '11px 0' }}>
          <StatusBadge tone={meta.tone}>{meta.label}</StatusBadge>
        </div>
        <dl className="kv" style={{ gridTemplateColumns: '130px 1fr', fontSize: 12.5 }}>
          {/* PLATFORM only: attribute the connector to its owning tenant — the mirrored name when
              served (Chunk 9), else the shortened UUID; full UUID always in the tooltip. */}
          {showTenant ? (
            <>
              <dt>Tenant</dt>
              <dd className="mono" title={tenantFull(c.tenant_id)}>
                {tenantName(c.tenant_name, c.tenant_id)}
              </dd>
            </>
          ) : null}
          <dt>Last seen</dt>
          <dd className="mono">{ago(c.last_seen_at)}</dd>
          <dt>Heartbeat</dt>
          <dd>{c.heartbeat_label ?? DASH}</dd>
          {/* Currently null for every connector (no machine cadence) → "—", never fabricated. */}
          <dt>Missed intervals</dt>
          <dd>{c.missed_intervals ?? DASH}</dd>
          {/* null for CSV (no auth) → "—"; a relative "in N days" only when the wire carries it. */}
          <dt>Auth expiry</dt>
          <dd>{until(c.auth_expires_at)}</dd>
          <dt>Rate limit</dt>
          <dd>{c.rate_limit_state ?? DASH}</dd>
        </dl>
      </div>
    </div>
  )
}

export function ConnectorHealth() {
  const { snapshot } = useAuth()
  const ops = snapshot !== null && isOps(snapshot)
  const [status, setStatus] = useState<StatusWire | null>(null)
  const [channel, setChannel] = useState<ChannelWire | null>(null)
  const [tenantFilter, setTenantFilter] = useState<string | null>(null) // PLATFORM only
  const q = useConnectorHealth(snapshot)
  const all: ConnectorHealthRow[] = q.data?.items ?? []
  const tenantOptions = ops ? distinctTenants(all.map((c) => c.tenant_id)) : []
  // tenant_id → name map for labelling the filter options by name (value stays tenant_id).
  const tenantNames = new Map<string | null, string | null>(all.map((c) => [c.tenant_id, c.tenant_name ?? null]))

  // KPI rollup: stale / attention (auth_expiring|rate_limited) / healthy. PENDING
  // is EXCLUDED from all three — a no-producer connector is not "healthy"; don't inflate the count.
  const staleCount = all.filter((c) => c.status === 'stale').length
  const attentionCount = all.filter(
    (c) => c.status === 'auth_expiring' || c.status === 'rate_limited',
  ).length
  const healthyCount = all.filter((c) => c.status === 'healthy').length
  const pendingCount = all.filter((c) => c.status === 'pending').length

  const shown = all.filter(
    (c) =>
      (status === null || c.status === status) &&
      (channel === null || c.channel === channel) &&
      (!ops || matchesTenant(c.tenant_id, tenantFilter)),
  )

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Connector Health</h1>
        </div>
      </div>

      <div className="toolbar">
        <label className="filter">
          Status{' '}
          <select
            aria-label="Status"
            value={status ?? ''}
            onChange={(e) => setStatus(e.target.value === '' ? null : (e.target.value as StatusWire))}
          >
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_META[s].label}
              </option>
            ))}
          </select>
        </label>
        <label className="filter">
          Method{' '}
          <select
            aria-label="Method"
            value={channel ?? ''}
            onChange={(e) =>
              setChannel(e.target.value === '' ? null : (e.target.value as ChannelWire))
            }
          >
            <option value="">All</option>
            {CHANNELS.map((ch) => (
              <option key={ch} value={ch}>
                {METHOD_META[ch].label}
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
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className="badge b-fail">{staleCount} stale</span>
          <span className="badge b-warn">{attentionCount} attention</span>
          <span className="badge b-ok">{healthyCount} healthy</span>
          {pendingCount > 0 ? <span className="badge b-mut">{pendingCount} pending</span> : null}
        </div>
      </div>

      {q.isPending ? (
        <LoadingState label="Loading connectors…" />
      ) : q.isError ? (
        <ErrorState message="Could not load connector health." />
      ) : all.length === 0 ? (
        <div className="empty">
          <h4>No connectors</h4>
          <div>No sources registered yet. Connect a data source to add one.</div>
        </div>
      ) : shown.length === 0 ? (
        <div className="empty">
          <h4>No matching connectors</h4>
          <div>No connectors match the current filters.</div>
        </div>
      ) : (
        <div className="grid g3">
          {shown.map((c) => (
            <ConnectorCard key={c.source_id} c={c} showTenant={ops} />
          ))}
        </div>
      )}
    </>
  )
}
