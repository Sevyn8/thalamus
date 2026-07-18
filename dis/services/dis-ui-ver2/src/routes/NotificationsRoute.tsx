import { Fragment, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'

import { isOps } from '../auth/AuthSnapshot'
import { useAuth } from '../auth/useAuth'
import { LoadingState } from '../components/states/LoadingState'
import { useAuditEvents } from '../lib/dis-ui-server/audit'
import { useConnectorHealth } from '../lib/dis-ui-server/connector-health'
import type { AttentionFilters, AttentionItem, AttentionSeverity } from '../lib/dis-ui-server/needs-attention'
import {
  applyFilters,
  deriveFromAudit,
  deriveFromConnectors,
  deriveFromQuarantine,
  deriveFromRuns,
  facetsOf,
  groupByTenant,
  hasActiveFilters,
  NO_FILTERS,
  sortAttention,
} from '../lib/dis-ui-server/needs-attention'
import { useQuarantineList } from '../lib/dis-ui-server/quarantine-api'
import { useRuns } from '../lib/dis-ui-server/runs'
import { SYSTEM_TENANT, tenantFull, tenantName } from '../lib/dis-ui-server/tenant-label'

// "Needs attention" — a READ-ONLY, STATELESS derived feed (replaces the old fixture-only
// Notifications route). It recomputes on load from FOUR existing endpoints and holds NO
// read/ack/severity/unread state (those were UI inventions; dropped). Rows are clickable and open
// the SHARED drawer pattern (.drawer/.drawer-scrim, role=dialog) used by Ingestion Runs / Audit /
// Sources; the deep-link action lives INSIDE the drawer, never inline on the row.
//
// SCOPE: the four endpoints see-all for a PLATFORM token. Since Chunk 1 added tenant_id to the
// rows, TENANT → the full per-item list; PLATFORM → the SAME items ATTRIBUTED per tenant (grouped
// by tenant_id via groupByTenant), each group a card headed by the tenant UUID (shortened, full in
// tooltip — no friendly name; that is Chunk 9). Null-tenant audit system rows → a "System /
// platform" group.

const SEV_BADGE: Record<AttentionSeverity, string> = { error: 'b-fail', warning: 'b-warn', info: 'b-info' }
// tenantShort / tenantFull / SYSTEM_TENANT now come from the shared tenant-label util (Chunk 3),
// so this view and the four fleet surfaces render tenant attribution identically.

function formatAt(at: string | null): string {
  if (at === null) return '—'
  const d = new Date(at)
  return Number.isNaN(d.getTime())
    ? at
    : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

// The row-click detail drawer — reuses the shared .drawer/.drawer-scrim slide-over (Esc + scrim
// close, panel focus, dialog aria), identical to RunDetail (IngestionRuns) and AuditDetail. The
// action button is a react-router Link in the .dft footer — deep-links to an EXISTING surface only.
function AttentionDetail({ item, onClose }: { item: AttentionItem | null; onClose: () => void }) {
  const open = item !== null
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

  const r = item
  return (
    <>
      <div className={open ? 'drawer-scrim on' : 'drawer-scrim'} onClick={onClose} />
      <div
        className={open ? 'drawer on' : 'drawer'}
        role="dialog"
        aria-modal="true"
        aria-hidden={!open}
        aria-label="Needs attention detail"
        tabIndex={-1}
        ref={panelRef}
      >
        {r !== null ? (
          <>
            <div className="dhd">
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9, flexWrap: 'wrap' }}>
                  <h3>{r.title}</h3>
                  <span className={`badge ${SEV_BADGE[r.severity]}`}>{r.severity}</span>
                </div>
                <div className="sub" style={{ marginTop: 3 }}>
                  {r.context}
                </div>
              </div>
              <button className="iconbtn" onClick={onClose} aria-label="Close detail">
                ×
              </button>
            </div>

            <div className="dbd">
              <div className="detsec">
                <h4>Detail</h4>
                <dl className="kv">
                  {r.detail.map((d) => (
                    <Fragment key={d.label}>
                      <dt>{d.label}</dt>
                      <dd>{d.value}</dd>
                    </Fragment>
                  ))}
                </dl>
              </div>
            </div>

            {/* Action lives in the drawer footer (never inline on the row): a deep-link to an
                existing ver2 surface. Navigating closes the drawer. */}
            <div className="dft">
              <Link className="btn pri" to={r.link.to} onClick={onClose}>
                {r.link.label}
              </Link>
            </div>
          </>
        ) : null}
      </div>
    </>
  )
}

export function NotificationsRoute() {
  const { snapshot } = useAuth()
  const ops = snapshot !== null && isOps(snapshot)
  const [selected, setSelected] = useState<AttentionItem | null>(null)
  // PLATFORM triage state (client-side only; ignored by the TENANT view). Filters combine AND;
  // group-by-tenant is a VIEW option (off = flat table, on = the per-tenant grouped cards).
  const [filters, setFilters] = useState<AttentionFilters>(NO_FILTERS)
  const [groupByOn, setGroupByOn] = useState(false)

  // The four sources. Each fires for both TENANT and PLATFORM (enabled on snapshot!=null; see-all
  // handles PLATFORM scoping server-side). Audit is pre-scoped to failures.
  const runs = useRuns(snapshot)
  const connectors = useConnectorHealth(snapshot)
  const audit = useAuditEvents(snapshot, { outcome: 'failure' })
  const quarantine = useQuarantineList(snapshot, {})

  // Derive per source (independent) then combine + sort. A source with no data yet contributes
  // nothing; it does not blank the others.
  const items = sortAttention([
    ...deriveFromRuns(runs.data?.items ?? []),
    ...deriveFromConnectors(connectors.data?.items ?? []),
    ...deriveFromAudit(audit.data?.items ?? []),
    ...deriveFromQuarantine(quarantine.data),
  ])
  // Chunk 9-FE: tenant_id → name map from the derived items, for labelling the tenant filter/chip
  // and the per-tenant group headers by name (grouping VALUE stays tenant_id — logic unchanged).
  const tenantNames = new Map(items.map((i) => [i.tenant_id, i.tenant_name ?? null]))

  const sources = [
    { key: 'ingestion runs', q: runs },
    { key: 'connector health', q: connectors },
    { key: 'audit', q: audit },
    { key: 'quarantine', q: quarantine },
  ]
  const allPending = sources.every((s) => s.q.isPending)
  const failedSources = sources.filter((s) => s.q.isError).map((s) => s.key)

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Needs Attention</h1>
          <div className="sub">
            {ops
              ? 'Fleet-wide items that need attention across all tenants.'
              : 'Items that need your attention right now.'}
          </div>
        </div>
      </div>

      {/* Per-source honesty: one source failing shows a soft note but never blanks the feed. */}
      {failedSources.length > 0 ? (
        <div className="warnbox" role="note" style={{ marginBottom: 12 }}>
          Couldn’t reach: {failedSources.join(', ')}. Showing what loaded.
        </div>
      ) : null}

      {allPending ? <LoadingState label="Checking what needs attention…" /> : ops ? platformView() : tenantView()}

      <AttentionDetail item={selected} onClose={() => setSelected(null)} />
    </>
  )

  // One clickable feed row (opens the SHARED drawer; NO inline action — the action is in the
  // drawer). Reused by the TENANT list and every PLATFORM tenant group so the row/drawer behaviour
  // is identical across both.
  function itemRows(list: AttentionItem[]) {
    return list.map((item) => (
      <tr
        key={item.id}
        className="click"
        tabIndex={0}
        onClick={() => setSelected(item)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setSelected(item)
          }
        }}
      >
        <td>
          <span className={`badge ${SEV_BADGE[item.severity]}`}>{item.severity}</span>
        </td>
        <td className="pri-name">{item.title}</td>
        <td className="id">{item.context}</td>
      </tr>
    ))
  }

  function feedTable(list: AttentionItem[]) {
    return (
      <div style={{ overflow: 'auto' }}>
        <table className="tbl">
          <thead>
            <tr>
              <th>Severity</th>
              <th>Item</th>
              <th>Context</th>
            </tr>
          </thead>
          <tbody>{itemRows(list)}</tbody>
        </table>
      </div>
    )
  }

  function emptyState() {
    return (
      <div className="empty">
        <h4>Nothing needs attention right now</h4>
        <div>Runs, connectors, quarantine and audit are all clear.</div>
      </div>
    )
  }

  // The flat FLEET table (PLATFORM default): Severity · Item · Tenant · Context · Time. Rows are
  // attributable without grouping (Tenant column, shortened UUID + full tooltip) and clickable →
  // the same shared drawer.
  function fleetTable(list: AttentionItem[]) {
    return (
      <div className="card">
        <div style={{ overflow: 'auto' }}>
          <table className="tbl">
            <thead>
              <tr>
                <th>Severity</th>
                <th>Item</th>
                <th>Tenant</th>
                <th>Context</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {list.map((item) => (
                <tr
                  key={item.id}
                  className="click"
                  tabIndex={0}
                  onClick={() => setSelected(item)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      setSelected(item)
                    }
                  }}
                >
                  <td>
                    <span className={`badge ${SEV_BADGE[item.severity]}`}>{item.severity}</span>
                  </td>
                  <td className="pri-name">{item.title}</td>
                  <td className="id" title={tenantFull(item.tenant_id)}>
                    {tenantName(item.tenant_name, item.tenant_id)}
                  </td>
                  <td className="id">{item.context}</td>
                  <td className="id">{formatAt(item.at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    )
  }

  // The per-tenant grouped cards (Chunk 2-attribution), now a VIEW OPTION behind the group-by
  // toggle rather than the forced structure. Renders over whatever list it is given (filtered).
  function groupedCards(list: AttentionItem[]) {
    return (
      <>
        {groupByTenant(list).map((group) => (
          <div className="card" key={group.tenantId ?? 'system'} style={{ marginBottom: 12 }}>
            <div className="hd">
              <h3 title={tenantFull(group.tenantId)}>
                {group.tenantId === null
                  ? 'System / platform'
                  : `Tenant ${tenantName(group.items[0]?.tenant_name ?? null, group.tenantId)}`}
              </h3>
              <span className="badge b-mut">{group.items.length}</span>
            </div>
            {feedTable(group.items)}
          </div>
        ))}
      </>
    )
  }

  // PLATFORM: a filterable triage view over the see-all items. DEFAULT is a single flat table
  // (severity-sorted, not pre-grouped); a group-by-tenant toggle switches to the grouped cards.
  // Filters (severity / type / tenant) auto-populate from the items present and combine AND, all
  // client-side over the already-fetched items — no endpoint per filter.
  function platformView() {
    if (items.length === 0) return emptyState()
    const facets = facetsOf(items)
    const filtered = applyFilters(items, filters)
    const active = hasActiveFilters(filters)
    return (
      <>
        <div className="toolbar">
          {/* Severity — a segmented control, auto-populated with the severities present. */}
          <div className="segment" role="group" aria-label="Severity">
            <button type="button" className={filters.severity === null ? 'on' : ''} onClick={() => setFilters((f) => ({ ...f, severity: null }))}>
              All
            </button>
            {facets.severities.map((s) => (
              <button key={s} type="button" className={filters.severity === s ? 'on' : ''} onClick={() => setFilters((f) => ({ ...f, severity: s }))}>
                {s}
              </button>
            ))}
          </div>
          {/* Type — auto-populated from the distinct typeLabels present. */}
          <label className="filter">
            Type{' '}
            <select aria-label="Type" value={filters.typeLabel ?? ''} onChange={(e) => setFilters((f) => ({ ...f, typeLabel: e.target.value === '' ? null : e.target.value }))}>
              <option value="">All</option>
              {facets.types.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          {/* Tenant — auto-populated from the distinct tenant_ids present. Labels are shortened
              UUIDs (full in each option's title) until tenant_name lands (Chunk 9). */}
          <label className="filter">
            Tenant{' '}
            <select aria-label="Tenant" value={filters.tenant ?? ''} onChange={(e) => setFilters((f) => ({ ...f, tenant: e.target.value === '' ? null : e.target.value }))}>
              <option value="">All</option>
              {facets.tenants.map((t) => {
                const value = t ?? SYSTEM_TENANT
                return (
                  <option key={value} value={value} title={tenantFull(t)}>
                    {tenantName(tenantNames.get(t) ?? null, t)}
                  </option>
                )
              })}
            </select>
          </label>
          {/* View toggle: flat table (default) vs the per-tenant grouped cards. */}
          <div className="segment" role="group" aria-label="Group by tenant">
            <button type="button" className={!groupByOn ? 'on' : ''} onClick={() => setGroupByOn(false)}>
              Flat
            </button>
            <button type="button" className={groupByOn ? 'on' : ''} onClick={() => setGroupByOn(true)}>
              By tenant
            </button>
          </div>
        </div>

        {/* Active-filter chips + clear-all (only when a filter is set). */}
        {active ? (
          <div className="toolbar" aria-label="Active filters">
            {filters.severity !== null ? (
              <button type="button" className="badge b-mut" onClick={() => setFilters((f) => ({ ...f, severity: null }))}>
                severity: {filters.severity} ✕
              </button>
            ) : null}
            {filters.typeLabel !== null ? (
              <button type="button" className="badge b-mut" onClick={() => setFilters((f) => ({ ...f, typeLabel: null }))}>
                type: {filters.typeLabel} ✕
              </button>
            ) : null}
            {filters.tenant !== null ? (
              <button
                type="button"
                className="badge b-mut"
                title={tenantFull(filters.tenant === SYSTEM_TENANT ? null : filters.tenant)}
                onClick={() => setFilters((f) => ({ ...f, tenant: null }))}
              >
                tenant:{' '}
                {tenantName(
                  tenantNames.get(filters.tenant === SYSTEM_TENANT ? null : filters.tenant) ?? null,
                  filters.tenant === SYSTEM_TENANT ? null : filters.tenant,
                )}{' '}
                ✕
              </button>
            ) : null}
            <button type="button" className="btn sm" onClick={() => setFilters(NO_FILTERS)}>
              Clear all
            </button>
          </div>
        ) : null}

        {filtered.length === 0 ? (
          <div className="empty">
            <h4>No items match these filters</h4>
            <div>Adjust or clear the filters to see fleet items.</div>
          </div>
        ) : groupByOn ? (
          groupedCards(filtered)
        ) : (
          fleetTable(filtered)
        )}
      </>
    )
  }

  // TENANT: the full per-item list (its own slice; unchanged).
  function tenantView() {
    if (items.length === 0) return emptyState()
    return <div className="card">{feedTable(items)}</div>
  }
}
