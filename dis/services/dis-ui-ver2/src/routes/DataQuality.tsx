import { useEffect, useRef, useState } from 'react'

import { isOps } from '../auth/AuthSnapshot'
import { useAuth } from '../auth/useAuth'
import { ErrorState } from '../components/states/ErrorState'
import { LoadingState } from '../components/states/LoadingState'
import type { QuarantineFailure, StageWire, StatusWire } from '../lib/dis-ui-server/quarantine-api'
import { useQuarantineDetail, useQuarantineList } from '../lib/dis-ui-server/quarantine-api'
import { distinctTenants, matchesTenant, SYSTEM_TENANT, tenantFull, tenantName } from '../lib/dis-ui-server/tenant-label'

// Data Quality & History (tenant). REAL (mode-aware): the quarantine list (GET /api/v1/quarantine)
// and the per-item DETAIL (GET /api/v1/quarantine/{id}), wired to QuarantineDetail. Slice 53a
// consumes 52b's store identity (store_name) + structured failures[]: the list is a lean triage
// queue (Store · Source · What failed · Stage · When · Status — no value/column, the list contract
// carries neither), and the drawer puts the offending VALUE front and centre via a failure hero
// that degrades honestly (Option A: a null value OMITS its row, never an "empty" chip). Resolve /
// Dismiss are INERT — no write endpoint exists yet (D82). The PLATFORM FleetView is unchanged.

// error_reason (a FailureCode) -> a human phrase for the list "What failed" column and the drawer
// title. Unknown codes fall back to a readable Title Case form (no silent default).
const REASON_HUMAN: Record<string, string> = {
  VALIDATION_ROW_FAILED: 'Row failed validation',
  POST_VALIDATION_FAILED: 'Row failed validation',
  PRE_VALIDATION_FAILED: "File shape doesn't match the source",
  MAPPING_EXECUTION_FAILED: 'Mapping transform failed',
}
function humanizeReason(code: string): string {
  const known = REASON_HUMAN[code]
  if (known !== undefined) return known
  return code
    .toLowerCase()
    .split('_')
    .map((w) => (w.length > 0 ? w[0].toUpperCase() + w.slice(1) : w))
    .join(' ')
}

// Status -> badge class. Only 'open' occurs today; 'resolved' is a real wire member but unreachable
// until a resolve-write path exists (D82). No 'dismissed' key — the backend collapses DB DISMISSED
// to wire 'resolved' (schemas/quarantine.py), so it never reaches the client.
const STATUS_BADGE: Record<StatusWire, string> = {
  open: 'b-fail',
  resolved: 'b-ok',
}

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function KV({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  )
}

// The failure hero: one failure element rendered value-front-and-centre, degrading HONESTLY.
// Every optional field is present-but-null on the wire -> decide each row with !== null (never
// truthiness, so a transform_index/row_index of 0 is kept). Option A: when value is null the Value
// row is OMITTED entirely (null means "not captured for this failure type", not "blank") — we do
// NOT render an "empty"/dash chip that would falsely imply the field was blank.
function FailureHero({ f }: { f: QuarantineFailure }) {
  const col = f.source_column ?? f.column
  return (
    <dl className="fail-hero">
      {col !== null ? (
        <div className="fh-row">
          <dt>Column</dt>
          <dd>
            <code className="mono">{col}</code>
          </dd>
        </div>
      ) : null}
      {f.row_index !== null ? (
        <div className="fh-row">
          <dt>Row</dt>
          {/* !== null (never truthiness) so a legitimate row offset of 0 is kept, not dropped. */}
          <dd>{f.row_index}</dd>
        </div>
      ) : null}
      {f.value !== null ? (
        <div className="fh-row">
          <dt>Value</dt>
          <dd>
            <code className="mono">{f.value}</code>
          </dd>
        </div>
      ) : null}
      {f.expected_format !== null ? (
        <div className="fh-row">
          <dt>Expected</dt>
          <dd>{f.expected_format}</dd>
        </div>
      ) : null}
      <div className="fh-row">
        <dt>Reason</dt>
        <dd>{f.reason}</dd>
      </div>
      <div className="fh-row">
        <dt>Check</dt>
        <dd>
          <code className="mono">{f.check}</code>
        </dd>
      </div>
    </dl>
  )
}

// Quarantine detail as a right-side drawer, always-mounted (Amit's pattern): scrim + `.on` toggle,
// role=dialog/aria-modal, aria-hidden derived from openness, Escape via a window keydown listener,
// focus on open. Openness is derived (`itemId !== null`), no separate isOpen. Body order: failure
// hero -> per-cell table (when >1 failure) -> one-line kind context -> "Where it came from" kv ->
// inert Resolve/Dismiss + "not yet" note (replacing the old static warnbox).
// `readOnly` hides the (inert) Resolve/Dismiss footer entirely — used by the PLATFORM fleet view,
// where cross-tenant mutation is out of scope (Sanjeev's RLS/policy, slice-25). The tenant view
// leaves it unset, keeping the inert-but-visible actions.
function GateFailureDetail({
  itemId,
  onClose,
  readOnly = false,
}: {
  itemId: string | null
  onClose: () => void
  readOnly?: boolean
}) {
  const { snapshot } = useAuth()
  const q = useQuarantineDetail(snapshot, itemId)
  const open = itemId !== null
  const panelRef = useRef<HTMLDivElement>(null)
  const d = q.data

  useEffect(() => {
    if (!open) return
    panelRef.current?.focus()
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <>
      <div className={open ? 'drawer-scrim on' : 'drawer-scrim'} onClick={onClose} />
      <div
        className={open ? 'drawer on' : 'drawer'}
        role="dialog"
        aria-modal="true"
        aria-hidden={!open}
        aria-label="Quarantine detail"
        tabIndex={-1}
        ref={panelRef}
      >
        <div className="dhd">
          <div style={{ flex: 1, minWidth: 0 }}>
            {d !== undefined ? (
              <>
                <div
                  className="mono"
                  style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 6, wordBreak: 'break-all' }}
                >
                  {d.id}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9, flexWrap: 'wrap' }}>
                  <span className="badge b-mut">{d.kind}</span>
                  <h3>{humanizeReason(d.error_reason)}</h3>
                </div>
                <div className="sub" style={{ marginTop: 6 }}>
                  {d.source} → {d.store_name ?? '—'} ·{' '}
                  {d.mapping_version !== null ? `mapping v${d.mapping_version}` : 'pre-lookup'} ·{' '}
                  {formatWhen(d.failed_at)}
                </div>
              </>
            ) : (
              <h3>Quarantine detail</h3>
            )}
          </div>
          <button className="iconbtn" onClick={onClose} aria-label="Close drawer">
            ×
          </button>
        </div>

        <div className="dbd">
          {open && q.isPending ? <LoadingState label="Loading quarantine detail…" /> : null}
          {q.isError ? <ErrorState message="Could not load this item." /> : null}
          {d !== undefined ? (
            <>
              {d.failures.length > 0 ? (
                <div className="detsec">
                  <h4>What failed</h4>
                  <FailureHero f={d.failures[0]} />
                </div>
              ) : null}

              {d.failures.length > 1 ? (
                <div className="detsec">
                  <h4>All failing cells</h4>
                  <div className="card">
                    <div style={{ overflow: 'auto' }}>
                      <table className="tbl">
                        <thead>
                          <tr>
                            <th>Column</th>
                            <th>Value</th>
                            <th>Expected</th>
                          </tr>
                        </thead>
                        <tbody>
                          {d.failures.map((f, i) => (
                            <tr key={`${f.column ?? f.check}-${i}`}>
                              <td className="id">
                                {f.source_column ?? f.column ?? <span className="mut">—</span>}
                              </td>
                              <td className="id">
                                {f.value !== null ? f.value : <span className="mut">—</span>}
                              </td>
                              <td>
                                {f.expected_format !== null ? (
                                  f.expected_format
                                ) : (
                                  <span className="mut">—</span>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              ) : null}

              <div className="note" style={{ marginBottom: 16 }}>
                {d.kind === 'chunk'
                  ? 'Whole-batch failure — every row in this upload was held because the file didn’t match the source shape.'
                  : 'This single row was held; the rest of the upload continued.'}
              </div>

              <div className="detsec">
                <h4>Where it came from</h4>
                <dl className="kv">
                  <KV label="Store">{d.store_name ?? <span className="mut">—</span>}</KV>
                  <KV label="Source">{d.source}</KV>
                  <KV label="Failed at stage">{d.failure_stage}</KV>
                  <KV label="Trace">
                    <span className="mono">{d.trace_id}</span>
                  </KV>
                  <KV label="Failed">{formatWhen(d.failed_at)}</KV>
                  <KV label="Mapping">
                    {d.mapping_version !== null ? `v${d.mapping_version}` : <span className="mut">—</span>}
                  </KV>
                </dl>
              </div>

              <div className="detsec">
                <h4>Context</h4>
                <div className="mono" style={{ fontSize: 12 }}>
                  {d.error_context}
                </div>
              </div>
            </>
          ) : null}
        </div>

        {/* Mutate footer — omitted entirely in readOnly (fleet) mode: no cross-tenant resolve/dismiss.
            In tenant mode it renders inert (D82: no write path exists yet). */}
        {readOnly ? null : (
          <div className="dft">
            <div className="actionbar">
              <button className="btn pri" disabled aria-disabled="true">
                Mark resolved
              </button>
              <button className="btn ghost" disabled aria-disabled="true">
                Dismiss
              </button>
              <span className="mut">Records who &amp; when — not yet wired</span>
            </div>
            <div className="warnbox" role="note" style={{ marginTop: 12 }}>
              <b>Not yet:</b> correcting the value in place, applying a default, or replaying fixed
              rows is future work. Resolve / Dismiss will record the decision; automated fix &amp;
              replay is future.
            </div>
          </div>
        )}
      </div>
    </>
  )
}

function TenantView() {
  const { snapshot } = useAuth()
  const q = useQuarantineList(snapshot, {})
  const [selected, setSelected] = useState<string | null>(null)
  if (q.isPending) return <LoadingState label="Loading quarantine…" />
  if (q.isError) return <ErrorState message="Could not load quarantine." />
  const items = q.data?.items ?? []
  return (
    <>
      <div className="note" style={{ marginBottom: 14 }}>
        Rows that failed validation for your tenant. Select a row to see the offending value.
      </div>
      <div className="card">
        <div className="hd">
          <h3>Quarantined rows</h3>
          <span className="badge b-fail">{q.data?.open_count ?? 0} open</span>
        </div>
        {items.length === 0 ? (
          <div className="bd">
            <div className="empty">
              <h4>Nothing quarantined</h4>
              <div>No rows failed validation in this window.</div>
            </div>
          </div>
        ) : (
          <div style={{ overflow: 'auto' }}>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Store</th>
                  <th>Source</th>
                  <th>What failed</th>
                  <th>Stage</th>
                  <th>When</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {items.map((r) => (
                  <tr
                    key={r.id}
                    className="click"
                    tabIndex={0}
                    onClick={() => setSelected(r.id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setSelected(r.id)
                      }
                    }}
                    aria-selected={selected === r.id}
                  >
                    <td className="pri-name">
                      {r.store_name ?? <span className="mut">—</span>}
                    </td>
                    <td>
                      <div className="pri-name">{r.source}</div>
                      <div className="subline">
                        {r.source_id} <span className="badge b-mut">{r.kind}</span>
                      </div>
                    </td>
                    <td>{humanizeReason(r.error_reason)}</td>
                    <td className="id">{r.failure_stage}</td>
                    <td>{formatWhen(r.failed_at)}</td>
                    <td>
                      <span className={`badge ${STATUS_BADGE[r.status]}`}>{r.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <GateFailureDetail itemId={selected} onClose={() => setSelected(null)} />
    </>
  )
}

// PLATFORM fleet quarantine (Chunk 4): the REAL GET /quarantine endpoint (useQuarantineList,
// quarantine-api.ts) SEE-ALLS cross-tenant for a PLATFORM token, so there is no separate "fleet"
// route — the tenant endpoint returns every tenant's rows under a PLATFORM scope. We render them as
// a flat, filterable triage table attributed by tenant_id (Chunk 1), READ-ONLY: no cross-tenant
// resubmit/resolve (that mutation is Sanjeev's RLS/policy, slice-25) — the detail drawer opens in
// readOnly mode. Filters (Tenant + Failure type) auto-populate from the rows present, combine AND.
function FleetView() {
  const { snapshot } = useAuth()
  const q = useQuarantineList(snapshot, {})
  const [selected, setSelected] = useState<string | null>(null)
  const [tenantFilter, setTenantFilter] = useState<string | null>(null)
  const [stageFilter, setStageFilter] = useState<StageWire | null>(null)

  if (q.isPending) return <LoadingState label="Loading fleet quarantine…" />
  if (q.isError) return <ErrorState message="Could not load fleet quarantine." />

  const items = q.data?.items ?? []
  const tenantOptions = distinctTenants(items.map((r) => r.tenant_id))
  // Chunk 9-FE: tenant_id → name map for labelling the filter options + chip by name (value stays tenant_id).
  const tenantNames = new Map<string | null, string | null>(items.map((r) => [r.tenant_id, r.tenant_name ?? null]))
  const stageOptions = [...new Set(items.map((r) => r.failure_stage))].sort((a, b) => a.localeCompare(b))
  const filtered = items.filter(
    (r) => matchesTenant(r.tenant_id, tenantFilter) && (stageFilter === null || r.failure_stage === stageFilter),
  )
  const active = tenantFilter !== null || stageFilter !== null

  return (
    <>
      <div className="note" style={{ marginBottom: 14 }}>
        Quarantined rows across all tenants (read-only). Select a row to see the offending value.
      </div>

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
        <label className="filter">
          Failure type{' '}
          <select
            aria-label="Failure type"
            value={stageFilter ?? ''}
            onChange={(e) => setStageFilter(e.target.value === '' ? null : (e.target.value as StageWire))}
          >
            <option value="">All</option>
            {stageOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>

      {active ? (
        <div className="toolbar" aria-label="Active filters">
          {tenantFilter !== null ? (
            <button
              type="button"
              className="badge b-mut"
              title={tenantFull(tenantFilter === SYSTEM_TENANT ? null : tenantFilter)}
              onClick={() => setTenantFilter(null)}
            >
              tenant:{' '}
              {tenantName(
                tenantNames.get(tenantFilter === SYSTEM_TENANT ? null : tenantFilter) ?? null,
                tenantFilter === SYSTEM_TENANT ? null : tenantFilter,
              )}{' '}
              ✕
            </button>
          ) : null}
          {stageFilter !== null ? (
            <button type="button" className="badge b-mut" onClick={() => setStageFilter(null)}>
              type: {stageFilter} ✕
            </button>
          ) : null}
          <button
            type="button"
            className="btn sm"
            onClick={() => {
              setTenantFilter(null)
              setStageFilter(null)
            }}
          >
            Clear all
          </button>
        </div>
      ) : null}

      <div className="card">
        <div className="hd">
          <h3>Fleet quarantine</h3>
          <span className="badge b-fail">{q.data?.open_count ?? 0} open</span>
        </div>
        {items.length === 0 ? (
          <div className="bd">
            <div className="empty">
              <h4>Nothing quarantined</h4>
              <div>No rows failed validation across the fleet in this window.</div>
            </div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="bd">
            <div className="empty">
              <h4>No items match these filters</h4>
              <div>Adjust or clear the filters to see fleet rows.</div>
            </div>
          </div>
        ) : (
          <div style={{ overflow: 'auto' }}>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Tenant</th>
                  <th>Store</th>
                  <th>Source</th>
                  <th>What failed</th>
                  <th>Stage</th>
                  <th>When</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr
                    key={r.id}
                    className="click"
                    tabIndex={0}
                    onClick={() => setSelected(r.id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setSelected(r.id)
                      }
                    }}
                    aria-selected={selected === r.id}
                  >
                    <td className="id" title={tenantFull(r.tenant_id)}>
                      {tenantName(r.tenant_name, r.tenant_id)}
                    </td>
                    <td className="pri-name">{r.store_name ?? <span className="mut">—</span>}</td>
                    <td>
                      <div className="pri-name">{r.source}</div>
                      <div className="subline">
                        {r.source_id} <span className="badge b-mut">{r.kind}</span>
                      </div>
                    </td>
                    <td>{humanizeReason(r.error_reason)}</td>
                    <td className="id">{r.failure_stage}</td>
                    <td>{formatWhen(r.failed_at)}</td>
                    <td>
                      <span className={`badge ${STATUS_BADGE[r.status]}`}>{r.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Read-only drill-in: reuses the tenant detail drawer with readOnly (no resolve/dismiss). */}
      <GateFailureDetail itemId={selected} onClose={() => setSelected(null)} readOnly />
    </>
  )
}

export function DataQuality() {
  const { snapshot } = useAuth()
  const ops = snapshot !== null && isOps(snapshot)
  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Data Quality &amp; History</h1>
          <div className="sub">
            {ops
              ? 'Fleet-wide quarantine across all tenants.'
              : 'Rows that failed validation for your tenant.'}
          </div>
        </div>
      </div>
      {ops ? <FleetView /> : <TenantView />}
    </>
  )
}
