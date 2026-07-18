import { useMemo, useState } from 'react'
import { Link } from 'react-router'

import { isOps } from '../auth/AuthSnapshot'
import { useAuth } from '../auth/useAuth'
import { ErrorState } from '../components/states/ErrorState'
import { LoadingState } from '../components/states/LoadingState'
import { useAuditEvents } from '../lib/dis-ui-server/audit'
import { useConnectorHealth } from '../lib/dis-ui-server/connector-health'
import type { TenantMetrics } from '../lib/dis-ui-server/dashboard'
import { useDashboardMetrics } from '../lib/dis-ui-server/dashboard'
import { useMappingTemplates } from '../lib/dis-ui-server/mapping-templates'
import type { AttentionItem, AttentionSeverity } from '../lib/dis-ui-server/needs-attention'
import {
  deriveFromAudit,
  deriveFromConnectors,
  deriveFromQuarantine,
  deriveFromRuns,
  sortAttention,
} from '../lib/dis-ui-server/needs-attention'
import { useQuarantineList } from '../lib/dis-ui-server/quarantine-api'
import type { MethodWire, RunRow, StatusWire } from '../lib/dis-ui-server/runs'
import { useRuns } from '../lib/dis-ui-server/runs'
import { tenantFull, tenantName } from '../lib/dis-ui-server/tenant-label'
import { useTemplateTypes } from '../lib/dis-ui-server/template-types'

// Needs-attention summary: severity → badge class (mirrors the standalone surface's SEV_BADGE) and
// the compact top-N shown on the card (the rest live behind "View all"). The ITEMS themselves come
// from the shared needs-attention.ts derivation — no logic is duplicated here, only the badge map.
const SEV_BADGE: Record<AttentionSeverity, string> = { error: 'b-fail', warning: 'b-warn', info: 'b-info' }
const NEEDS_ATTENTION_MAX = 5

// Recent-runs card helpers (shared vocabulary with the Ingestion Runs surface).
const STATUS_BADGE: Record<StatusWire, string> = {
  succeeded: 'b-ok',
  quarantined: 'b-warn',
  failed: 'b-fail',
  processing: 'b-live',
}
const METHOD_LABEL: Record<MethodWire, string> = {
  csv_upload: 'Manual CSV',
  api: 'API',
  csv_erp: 'ERP CSV',
  reverse_api: 'Reverse API',
}
function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// A path-aware count (mirrors the Ingestion Runs CountCell): null -> "—" (honest absence, e.g. a
// processing/failed run never reached that terminal count), 0 -> muted zero, else the tinted number.
function countCell(value: number | null, cls: 'count-acc' | 'count-qua'): React.ReactNode {
  if (value === null) return <span className="mut">—</span>
  if (value === 0) return <span className="mut">0</span>
  return <span className={cls}>{value.toLocaleString()}</span>
}

// --- By-tenant breakdown (Chunk 6b): sort + honest rate rendering -----------------------------
type ByTenantSortKey = 'rows' | 'quarantined' | 'rate'

// Quarantine rate is a fraction (quarantined/received) or null when received==0. Render as a
// percentage; a null rate is an HONEST "—" (no denominator), never "0%" or "NaN".
function formatRate(rate: number | null): React.ReactNode {
  if (rate === null) return <span className="mut">—</span>
  return `${(rate * 100).toFixed(2)}%`
}

// The sortable value for a tenant row under the active key. Rate can be null (sorted last, below).
function sortValue(t: TenantMetrics, key: ByTenantSortKey): number | null {
  if (key === 'rows') return t.rows_ingested_24h
  if (key === 'quarantined') return t.quarantine_24h.quarantined_rows
  return t.quarantine_24h.rate
}

// A clickable, plain-styled sortable column header (no CSS additions; styled inline to read as a th).
function SortHeader({
  label,
  col,
  activeKey,
  dir,
  onSort,
}: {
  label: string
  col: ByTenantSortKey
  activeKey: ByTenantSortKey
  dir: 'asc' | 'desc'
  onSort: (c: ByTenantSortKey) => void
}): React.ReactNode {
  const active = activeKey === col
  return (
    <th aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button
        type="button"
        onClick={() => onSort(col)}
        style={{
          background: 'none',
          border: 0,
          padding: 0,
          font: 'inherit',
          color: 'inherit',
          cursor: 'pointer',
        }}
      >
        {label}
        {active ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}
      </button>
    </th>
  )
}

// Dashboard (index) — mockup KPI row + cards wired to REAL endpoints where the data exists.
// REAL: Sources connected (metrics.sources_connected), Rows ingested (rows_ingested_24h), Quality
// pass rate (derived from quarantine_24h), the per-template Flow table, and Recent ingestion runs
// (a bounded slice of GET /runs, D111). PENDING (L1, no data/route on main): Freshness-within-SLA
// (no cadence stored) and the Needs-attention alert feed — shown as clearly-marked placeholders,
// NOT fabricated numbers.
export function Dashboard() {
  const { snapshot } = useAuth()
  // Scope labeling (Chunk 5): /dashboard/metrics is scope-driven — a PLATFORM token gets see-all
  // fleet totals, a TENANT token its own totals (same endpoint, same fields). We only LABEL that
  // scope here; the values are exactly what the endpoint returns for the token (no data change, no
  // per-tenant breakdown — that is Chunk 6). Uses the shared isOps discriminator (userType==='PLATFORM').
  const ops = snapshot !== null && isOps(snapshot)
  const metrics = useDashboardMetrics(snapshot)
  const templates = useMappingTemplates(snapshot, null)
  const types = useTemplateTypes()
  const runs = useRuns(snapshot)
  // Recent-runs card: a bounded recent slice of the real GET /runs (no new endpoint/client).
  const recentRuns: RunRow[] = (runs.data?.items ?? []).slice(0, 5)

  // Needs-attention summary card: the SAME derived feed as the standalone /notifications surface
  // (needs-attention.ts) — reused, not duplicated. Reuses `runs` above + three more read hooks;
  // derives per source and sortAttention orders by severity then recency. PLATFORM see-all is
  // handled server-side, so the items + tenant attribution are identical to the standalone feed.
  const connectors = useConnectorHealth(snapshot)
  const audit = useAuditEvents(snapshot, { outcome: 'failure' })
  const quarantine = useQuarantineList(snapshot, {})
  const attentionPending = [runs, connectors, audit, quarantine].every((s) => s.isPending)
  const attentionItems: AttentionItem[] = sortAttention([
    ...deriveFromRuns(runs.data?.items ?? []),
    ...deriveFromConnectors(connectors.data?.items ?? []),
    ...deriveFromAudit(audit.data?.items ?? []),
    ...deriveFromQuarantine(quarantine.data),
  ])
  const topAttention = attentionItems.slice(0, NEEDS_ATTENTION_MAX)

  const typeLabel = (key: string): string =>
    (types.data ?? []).find((t) => t.key === key)?.display_name ?? key
  const flowByTemplate = new Map((metrics.data?.flow ?? []).map((f) => [f.template_id, f]))

  const q = metrics.data?.quarantine_24h
  const passRate =
    q !== undefined && q.received_rows > 0
      ? `${(((q.received_rows - q.quarantined_rows) / q.received_rows) * 100).toFixed(1)}%`
      : '—'

  // Per-tenant breakdown (Chunk 6b) — PLATFORM-only. Default sort: rows ingested, descending
  // (biggest tenants first); the quarantine-rate column lets ops surface the struggling tenants.
  const [sortKey, setSortKey] = useState<ByTenantSortKey>('rows')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const onSort = (c: ByTenantSortKey): void => {
    if (c === sortKey) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else {
      setSortKey(c)
      setSortDir('desc')
    }
  }
  const byTenant = useMemo<TenantMetrics[]>(() => metrics.data?.by_tenant ?? [], [metrics.data])
  const sortedByTenant = useMemo(() => {
    return [...byTenant].sort((a, b) => {
      const av = sortValue(a, sortKey)
      const bv = sortValue(b, sortKey)
      // A null rate (received==0) has no magnitude, so it always sorts LAST regardless of direction.
      if (av === null && bv === null) return 0
      if (av === null) return 1
      if (bv === null) return -1
      return sortDir === 'asc' ? av - bv : bv - av
    })
    // metrics.data is a stable react-query ref; re-sort only when the data or the sort changes.
  }, [byTenant, sortKey, sortDir])

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Operations Dashboard</h1>
          <div className="sub">
            {ops ? 'Fleet-wide metrics across all tenants.' : 'Metrics for your tenant.'}
          </div>
        </div>
        <div className="actions">
          <Link className="btn pri" to="/connect">
            Connect a data source
          </Link>
        </div>
      </div>

      {metrics.isError ? <ErrorState message="Could not load dashboard metrics." /> : null}

      {/* KPI row (mockup). Rows ingested + Quality pass rate are REAL (/dashboard/metrics);
          Sources = live template count; Freshness is pending (no cadence/SLA data on main). */}
      <div className="grid g4" style={{ marginBottom: 16 }}>
        <div className="kpi">
          <div className="top">Sources connected</div>
          <div className="val">
            {metrics.isPending ? '—' : metrics.data?.sources_connected}
          </div>
        </div>
        <div className="kpi">
          <div className="top">Rows ingested</div>
          <div className="val">
            {metrics.isPending ? '—' : metrics.data?.rows_ingested_24h.toLocaleString()}
            <span className="den">24h</span>
          </div>
        </div>
        <div className="kpi">
          <div className="top">Quality pass rate</div>
          <div className="val">{metrics.isPending ? '—' : passRate}</div>
          <div className="meta">
            {q !== undefined ? `${q.quarantined_rows.toLocaleString()} quarantined / ${q.received_rows.toLocaleString()} received` : null}
          </div>
        </div>
        <div className="kpi">
          <div className="top">Freshness within SLA</div>
          <div className="val" style={{ color: 'var(--text-3)' }}>—</div>
          <div className="meta">pending: no per-source cadence/SLA on backend</div>
        </div>
      </div>

      {/* By tenant (Chunk 6b) — PLATFORM-only per-tenant breakdown of the fleet 24h KPIs, consuming
          metrics.by_tenant (Chunk 6). Gated on isOps so a TENANT never sees it (its by_tenant is []
          anyway); within a PLATFORM view an empty by_tenant renders an honest empty state, not a
          hidden/broken section. Tenant labels use the shared tenant-label helper (shortened UUID +
          full-id tooltip) — no fabricated names (tenant_name is the later CM-join chunk). Sort:
          simple client-side (no existing header-sort pattern in the codebase); default rows-desc,
          click a header to sort, click again to flip; a null rate always sorts last. */}
      {ops ? (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="hd">
            <h3>By tenant</h3>
            <span className="badge b-mut">{byTenant.length}</span>
          </div>
          {byTenant.length === 0 ? (
            <div className="bd">
              <div className="empty">
                <h4>No per-tenant activity in the last 24h</h4>
                <div>No tenant ingested or quarantined data in the window.</div>
              </div>
            </div>
          ) : (
            <div style={{ overflow: 'auto' }}>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Tenant</th>
                    <SortHeader label="Rows ingested (24h)" col="rows" activeKey={sortKey} dir={sortDir} onSort={onSort} />
                    <SortHeader label="Quarantined (24h)" col="quarantined" activeKey={sortKey} dir={sortDir} onSort={onSort} />
                    <SortHeader label="Quarantine rate" col="rate" activeKey={sortKey} dir={sortDir} onSort={onSort} />
                  </tr>
                </thead>
                <tbody>
                  {sortedByTenant.map((t) => (
                    <tr key={t.tenant_id}>
                      <td className="id" title={tenantFull(t.tenant_id)}>
                        {tenantName(t.tenant_name, t.tenant_id)}
                      </td>
                      <td className="mono">{t.rows_ingested_24h.toLocaleString()}</td>
                      <td className="mono">{t.quarantine_24h.quarantined_rows.toLocaleString()}</td>
                      <td className="mono">{formatRate(t.quarantine_24h.rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : null}

      {/* Needs attention (wired to the derived feed) + Recent runs. */}
      <div className="grid g2" style={{ marginBottom: 16 }}>
        {/* Needs attention — a compact summary of the SAME derived feed as /notifications
            (needs-attention.ts). Top-N highest-severity items; each row deep-links to the relevant
            surface; "View all" opens the full Needs attention surface. Honest empty state; PLATFORM
            shows the owning tenant via the shared tenant-label helper. */}
        <div className="card">
          <div className="hd">
            <h3>Needs attention</h3>
            <Link className="btn sm" to="/notifications">
              View all
            </Link>
          </div>
          {attentionPending ? (
            <LoadingState label="Checking what needs attention…" />
          ) : attentionItems.length === 0 ? (
            <div className="bd">
              <div className="empty">
                <h4>Nothing needs attention right now</h4>
                <div>{ops ? 'No fleet items need attention right now.' : 'You’re all caught up.'}</div>
              </div>
            </div>
          ) : (
            <div className="bd">
              {topAttention.map((item) => (
                <Link
                  key={item.id}
                  to={item.link.to}
                  style={{
                    display: 'flex',
                    gap: 10,
                    alignItems: 'baseline',
                    padding: '8px 0',
                    borderTop: '1px solid var(--line)',
                    textDecoration: 'none',
                    color: 'inherit',
                  }}
                >
                  <span className={`badge ${SEV_BADGE[item.severity]}`}>{item.severity}</span>
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <div className="pri-name">{item.title}</div>
                    <div className="id" style={{ fontSize: 12, color: 'var(--text-3)' }}>
                      {ops ? (
                        <span title={tenantFull(item.tenant_id)}>{tenantName(item.tenant_name, item.tenant_id)} · </span>
                      ) : null}
                      {item.context}
                    </div>
                  </span>
                </Link>
              ))}
              {attentionItems.length > topAttention.length ? (
                <div style={{ padding: '10px 0 0', color: 'var(--text-3)', fontSize: 12 }}>
                  +{attentionItems.length - topAttention.length} more in{' '}
                  <Link to="/notifications">Needs attention</Link>
                </div>
              ) : null}
            </div>
          )}
        </div>
        {/* Recent ingestion runs — REAL: a bounded recent slice of GET /runs. Columns
            Run·Source·Status·Accepted/Quarantined·When. The rebuilt /runs carries the two real
            terminal counts (accepted + quarantined; the old 3-way Acc/Rev/Rej "needs review" bucket
            was dropped from the wire, D119). Honest "—" where a count is null (non-terminal run),
            same as the Ingestion Runs surface. */}
        <div className="card">
          <div className="hd">
            <h3>Recent ingestion runs</h3>
            <Link className="btn sm" to="/ingestion-runs">
              View all
            </Link>
          </div>
          {runs.isPending ? (
            <LoadingState label="Loading runs…" />
          ) : runs.isError ? (
            <ErrorState message="Could not load ingestion runs." />
          ) : recentRuns.length === 0 ? (
            <div className="bd">
              <div className="empty">
                <h4>No ingestion runs</h4>
                <div>No ingress events yet.</div>
              </div>
            </div>
          ) : (
            <div style={{ overflow: 'auto' }}>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Source</th>
                    <th>Status</th>
                    <th>Accepted / quarantined</th>
                    <th>When</th>
                  </tr>
                </thead>
                <tbody>
                  {recentRuns.map((r) => (
                    <tr key={r.id}>
                      <td className="id" title={r.id}>
                        {r.id.slice(0, 8)}
                      </td>
                      <td>
                        <span className="mono" style={{ fontSize: 12, color: 'var(--text-2)' }}>
                          {METHOD_LABEL[r.method]}
                        </span>{' '}
                        {r.source_id}
                      </td>
                      <td>
                        <span className={`badge ${STATUS_BADGE[r.status]}`}>{r.status}</span>
                      </td>
                      {/* Real 2-way terminal counts from /runs; "—" when null (non-terminal). */}
                      <td className="id">
                        {countCell(r.accepted, 'count-acc')} / {countCell(r.quarantined, 'count-qua')}
                      </td>
                      <td className="id" title={r.received_at}>
                        {formatWhen(r.received_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Flow by template — REAL (/dashboard/metrics flow + /mapping-templates). */}
      <div className="card">
        <div className="hd">
          <h3>Flow &amp; quality (24h)</h3>
          <Link className="btn sm" to="/templates">
            Data Ingestion Templates
          </Link>
        </div>
        {templates.isPending ? (
          <LoadingState label="Loading templates…" />
        ) : templates.data === undefined || templates.data.length === 0 ? (
          <div className="bd">
            <div className="empty">
              <h4>No templates</h4>
              <div>Connect a data source to create a mapping template.</div>
            </div>
          </div>
        ) : (
          <div style={{ overflow: 'auto' }}>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Template</th>
                  <th>Source</th>
                  <th>Type</th>
                  <th>Rows 24h</th>
                  <th>Last received</th>
                </tr>
              </thead>
              <tbody>
                {templates.data.map((t) => {
                  const flow = flowByTemplate.get(t.template_id)
                  return (
                    <tr className="click" key={t.template_id}>
                      <td>
                        <Link className="pri-name" to={`/templates/${t.template_id}`}>
                          {t.template_name}
                        </Link>
                      </td>
                      <td className="id">{t.source_id}</td>
                      <td>
                        <span className="badge b-info">{typeLabel(t.template_type ?? '')}</span>
                      </td>
                      <td className="mono">{flow?.rows_24h ?? 0}</td>
                      <td className="id">
                        {flow?.last_received_at
                          ? new Date(flow.last_received_at).toISOString().slice(0, 10)
                          : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
