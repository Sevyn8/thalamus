import { useEffect, useRef, useState } from 'react'

import { isOps } from '../auth/AuthSnapshot'
import { useAuth } from '../auth/useAuth'
import { ErrorState } from '../components/states/ErrorState'
import { LoadingState } from '../components/states/LoadingState'
import type { MethodWire, RunRow, StatusWire, WindowWire } from '../lib/dis-ui-server/runs'
import { RUNS_PAGE_SIZE, useRuns } from '../lib/dis-ui-server/runs'
import { distinctTenants, matchesTenant, SYSTEM_TENANT, tenantFull, tenantName } from '../lib/dis-ui-server/tenant-label'

// Ingestion Runs — the combined operational runs surface wired to Sanjeev's rebuilt GET
// /api/v1/runs (20-field RunRow, D117-D125): a richer table (Store · Source · When · Status ·
// Input · Accepted · Quarantined · File), a per-run detail SLIDE-OVER that reads the already-fetched
// row (NO extra call — there is no GET /runs/{id}), and a KEYSET pager (D124: forward Next off
// next_cursor, page-stack Prev; a filter change resets the cursor so a stale one is never replayed).
//
// HONEST RENDERING (D119): real values where the wire carries them; per-column "—"/deferred labels
// where null (store / source / template / file / mapping version / published / completed). The two
// DERIVED fields are computed from present data only — sourceUnregistered = source_name==null, and
// the reconcile line from input_row_count vs accepted+quarantined (the wire does NOT guarantee they
// agree — two independent parsers; a gap is represented, never forced to reconcile). No fabricated
// numbers: fields the wire does not carry (e.g. per-reason quarantine breakdown, submitting user)
// are simply not shown — never invented.

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

const WINDOWS: WindowWire[] = ['24h', '7d', '30d']
const STATUSES: StatusWire[] = ['processing', 'succeeded', 'quarantined', 'failed']

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// Full timestamp for the detail timeline (null renders the caller's deferred label, never here).
function formatFull(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

// DERIVED (not a wire field): a source with no config.sources registry row resolves to a null name.
function sourceUnregistered(r: RunRow): boolean {
  return r.source_name === null
}

// DERIVED reconcile line. The wire exposes three INDEPENDENT numbers (input from the worker's
// DuckDB preflight; accepted/quarantined from the consumer's Polars parse) and never asserts they
// sum equal (D119). We state the split honestly and, when all three are known, either confirm they
// reconcile or represent the gap — we never force "reconciles to input" when it does not.
type ReconcileTone = 'ok' | 'warn' | 'fail' | 'mut'
const TONE_BOX: Record<ReconcileTone, string> = { ok: 'okbox', warn: 'warnbox', fail: 'failbox', mut: 'note' }

function reconcileLine(r: RunRow): { tone: ReconcileTone; text: string } {
  if (r.status === 'processing') {
    return { tone: 'mut', text: 'Run in progress — accepted and quarantined counts finalize when it completes.' }
  }
  if (r.status === 'failed') {
    const recv = r.input_row_count !== null ? ` ${r.input_row_count.toLocaleString()} rows were received, but` : ''
    return { tone: 'fail', text: `Run failed —${recv} nothing was committed to canonical.` }
  }
  const { input_row_count: n, accepted: a, quarantined: q } = r
  if (a === null && q === null) {
    return { tone: 'mut', text: 'No row counts were recorded for this run.' }
  }
  const acc = a ?? 0
  const qua = q ?? 0
  const split =
    acc > 0 && qua > 0
      ? `${acc.toLocaleString()} accepted · ${qua.toLocaleString()} quarantined`
      : qua > 0
        ? `${qua.toLocaleString()} quarantined`
        : `${acc.toLocaleString()} accepted`
  if (n === null) {
    return { tone: 'ok', text: `${split}. Input total was not recorded.` }
  }
  const sum = acc + qua
  if (sum === n) {
    return { tone: 'ok', text: `${split} — reconciles to ${n.toLocaleString()} rows received.` }
  }
  return {
    tone: 'warn',
    text: `${split} = ${sum.toLocaleString()}, but ${n.toLocaleString()} rows were received. These are independent preflight and parse counts — a gap can occur and is not an error.`,
  }
}

// A path-aware count cell: null -> "—" (honest absence), 0 -> muted zero, else the tinted number.
function CountCell({ value, kind }: { value: number | null; kind: 'acc' | 'qua' }) {
  if (value === null) return <span className="mut">—</span>
  if (value === 0) return <span className="mut">0</span>
  return <span className={kind === 'acc' ? 'count-acc' : 'count-qua'}>{value.toLocaleString()}</span>
}

// A key/value row in the detail panel; value falls back to a muted deferred label when absent.
function KV({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  )
}

function StatusPill({ r }: { r: RunRow }) {
  return (
    <>
      <span className={`badge ${STATUS_BADGE[r.status]}`}>{r.status}</span>
      {r.seen_before ? <span className="badge b-mut seen-flag">seen before</span> : null}
    </>
  )
}

// The per-run detail slide-over. Reads the in-hand row (NO fetch, no /runs/{id}). Kept mounted for
// the slide transition; `shown` retains the last row so content persists during the exit. Esc and
// scrim-click close; the panel takes focus on open and carries dialog aria.
function RunDetail({ run, onClose }: { run: RunRow | null; onClose: () => void }) {
  const open = run !== null
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

  const r = run
  const rec = r !== null ? reconcileLine(r) : null

  return (
    <>
      <div className={open ? 'drawer-scrim on' : 'drawer-scrim'} onClick={onClose} />
      <div
        className={open ? 'drawer on' : 'drawer'}
        role="dialog"
        aria-modal="true"
        aria-hidden={!open}
        aria-label="Ingestion run detail"
        tabIndex={-1}
        ref={panelRef}
      >
        {r !== null && rec !== null ? (
          <>
            <div className="dhd">
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9, flexWrap: 'wrap' }}>
                  <h3>
                    Run <span className="id">{r.id.slice(0, 8)}</span>
                  </h3>
                  <StatusPill r={r} />
                </div>
                <div className="sub" style={{ marginTop: 3 }}>
                  {(r.source_name ?? r.source_id) + ' → ' + (r.store_name ?? 'no store')} ·{' '}
                  {METHOD_LABEL[r.method]} · received {formatWhen(r.received_at)}
                </div>
              </div>
              <button className="iconbtn" onClick={onClose} aria-label="Close detail">
                ×
              </button>
            </div>

            <div className="dbd">
              {/* Summary counts */}
              <div className="detsummary">
                <div className="tile">
                  <div className="lbl">Total rows</div>
                  <div className="val">{r.input_row_count !== null ? r.input_row_count.toLocaleString() : '—'}</div>
                </div>
                <div className="tile">
                  <div className="lbl">Accepted</div>
                  <div className="val">
                    <CountCell value={r.accepted} kind="acc" />
                  </div>
                </div>
                <div className="tile">
                  <div className="lbl">Quarantined</div>
                  <div className="val">
                    <CountCell value={r.quarantined} kind="qua" />
                  </div>
                </div>
              </div>
              <div className={TONE_BOX[rec.tone]} style={{ marginBottom: 18 }} role="note">
                {rec.text}
              </div>

              {/* Identity */}
              <div className="detsec">
                <h4>Identity</h4>
                <dl className="kv">
                  <KV label="Store">
                    {r.store_name !== null ? (
                      <>
                        {r.store_name}
                        {r.store_id !== null ? <span className="id"> · {r.store_id}</span> : null}
                      </>
                    ) : (
                      <span className="mut">— identity deferred to the consumer</span>
                    )}
                  </KV>
                  <KV label="Source">
                    {sourceUnregistered(r) ? (
                      <>
                        <span className="id">{r.source_id}</span> <span className="mut">· unregistered source</span>
                      </>
                    ) : (
                      <>
                        {r.source_name}
                        <span className="id"> · {r.source_id}</span>
                      </>
                    )}
                  </KV>
                  <KV label="Method">{METHOD_LABEL[r.method]}</KV>
                  <KV label="File">
                    {r.file_name !== null ? (
                      <span className="id">{r.file_name}</span>
                    ) : (
                      <span className="mut">— (not captured)</span>
                    )}
                  </KV>
                  <KV label="Payload ref">
                    {r.source_payload_id !== null ? (
                      <span className="id">{r.source_payload_id}</span>
                    ) : (
                      <span className="mut">—</span>
                    )}
                  </KV>
                </dl>
              </div>

              {/* Mapping */}
              <div className="detsec">
                <h4>Mapping</h4>
                <dl className="kv">
                  <KV label="Template">
                    {r.template_name !== null ? (
                      <>
                        {r.template_name}
                        {r.template_id !== null ? <span className="id"> · {r.template_id.slice(0, 8)}</span> : null}
                      </>
                    ) : (
                      <span className="mut">— none applied</span>
                    )}
                  </KV>
                  <KV label="Mapping version">
                    {r.mapping_version !== null ? `v${r.mapping_version}` : <span className="mut">—</span>}
                  </KV>
                </dl>
              </div>

              {/* Timeline */}
              <div className="detsec">
                <h4>Timeline</h4>
                <dl className="kv">
                  <KV label="Received">{formatFull(r.received_at)}</KV>
                  <KV label="Published">
                    {r.published_at !== null ? formatFull(r.published_at) : <span className="mut">—</span>}
                  </KV>
                  <KV label="Completed">
                    {r.completed_at !== null ? formatFull(r.completed_at) : <span className="mut">— not yet</span>}
                  </KV>
                </dl>
              </div>

              {/* Trace & refs */}
              <div className="detsec">
                <h4>Trace &amp; refs</h4>
                <dl className="kv">
                  <KV label="Run id">
                    <span className="id">{r.id}</span>
                  </KV>
                  <KV label="Trace id">
                    <span className="id">{r.trace_id}</span>
                  </KV>
                  <KV label="Seen before">{r.seen_before ? 'Yes' : 'No'}</KV>
                </dl>
              </div>
            </div>
          </>
        ) : null}
      </div>
    </>
  )
}

export function IngestionRuns() {
  const { snapshot } = useAuth()
  const ops = snapshot !== null && isOps(snapshot)
  const [window, setWindow] = useState<WindowWire | null>(null)
  const [status, setStatus] = useState<StatusWire | null>(null)
  // PLATFORM-only tenant filter. Runs is KEYSET-paginated, so this filters CLIENT-SIDE over the
  // CURRENT page only (never pushed into the keyset query, which would break cursor stability) —
  // the toolbar notes this. TENANT view never sees it.
  const [tenantFilter, setTenantFilter] = useState<string | null>(null)
  // Keyset pagination (D124): a stack of the cursors used to reach each page (page 0 = no cursor).
  // Prev pops the stack; Next pushes the current page's next_cursor. Any filter change RESETS this,
  // so a cursor issued under one filter set is never replayed under another (the wire 422s on that).
  const [pageCursors, setPageCursors] = useState<(string | undefined)[]>([undefined])
  const [pageIndex, setPageIndex] = useState(0)
  const [selected, setSelected] = useState<RunRow | null>(null)

  const q = useRuns(
    snapshot,
    { window: window ?? undefined, status: status ?? undefined },
    RUNS_PAGE_SIZE,
    pageCursors[pageIndex],
  )
  const rows: RunRow[] = q.data?.items ?? []
  // The rows actually shown: PLATFORM tenant filter applied over the loaded page (client-side).
  const displayRows = ops ? rows.filter((r) => matchesTenant(r.tenant_id, tenantFilter)) : rows
  const tenantOptions = ops ? distinctTenants(rows.map((r) => r.tenant_id)) : []
  // Chunk 9-FE: tenant_id → name map from the loaded rows, for labelling the filter options by name
  // (option VALUE stays tenant_id — filter logic unchanged).
  const tenantNames = new Map<string | null, string | null>(rows.map((r) => [r.tenant_id, r.tenant_name ?? null]))
  const nextCursor = q.data?.next_cursor ?? null

  function resetPagination(): void {
    setPageCursors([undefined])
    setPageIndex(0)
  }
  function onWindow(w: WindowWire | null): void {
    setWindow(w)
    resetPagination()
  }
  function onStatus(s: StatusWire | null): void {
    setStatus(s)
    resetPagination()
  }
  function goPrev(): void {
    setPageIndex((i) => Math.max(0, i - 1))
  }
  function goNext(): void {
    if (nextCursor === null) return
    setPageCursors((prev) => [...prev.slice(0, pageIndex + 1), nextCursor])
    setPageIndex((i) => i + 1)
  }

  const processing = rows.filter((r) => r.status === 'processing').length

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Ingestion Runs</h1>
        </div>
      </div>

      {/* Filters wired to the real query params (window, status). Changing either resets the pager. */}
      <div className="toolbar">
        <div className="segment" role="group" aria-label="Time window">
          <button type="button" className={window === null ? 'on' : ''} onClick={() => onWindow(null)}>
            All time
          </button>
          {WINDOWS.map((w) => (
            <button key={w} type="button" className={window === w ? 'on' : ''} onClick={() => onWindow(w)}>
              {w}
            </button>
          ))}
        </div>
        <label className="filter">
          Status{' '}
          <select
            aria-label="Status"
            value={status ?? ''}
            onChange={(e) => onStatus(e.target.value === '' ? null : (e.target.value as StatusWire))}
          >
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        {/* PLATFORM only: tenant filter, auto-populated from the loaded page's tenant_ids. */}
        {ops ? (
          <>
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
            <span className="hint">Tenant filters the loaded page.</span>
          </>
        ) : null}
      </div>

      <div className="card">
        <div className="hd">
          <h3>Ingestion runs</h3>
          {processing > 0 ? (
            <span className="badge b-live">{processing} processing</span>
          ) : (
            <span className="badge b-mut">{rows.length}</span>
          )}
        </div>
        {q.isPending ? (
          <LoadingState label="Loading runs…" />
        ) : q.isError ? (
          <ErrorState message="Could not load ingestion runs." />
        ) : displayRows.length === 0 ? (
          <div className="bd">
            <div className="empty">
              <h4>No ingestion runs</h4>
              <div>No ingress events match the current filters.</div>
            </div>
          </div>
        ) : (
          <>
            <div style={{ overflow: 'auto' }}>
              <table className="tbl">
                <thead>
                  <tr>
                    {ops ? <th>Tenant</th> : null}
                    <th>Store</th>
                    <th>Source</th>
                    <th>When</th>
                    <th>Status</th>
                    <th>Input</th>
                    <th>Accepted</th>
                    <th>Quarantined</th>
                    <th>File</th>
                    <th aria-label="Open detail" />
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
                      <td>
                        {r.store_name !== null ? (
                          <div className="pri-name">{r.store_name}</div>
                        ) : (
                          <span className="mut">— no store · identity deferred</span>
                        )}
                      </td>
                      <td>
                        {sourceUnregistered(r) ? (
                          <>
                            <div className="pri-name id">{r.source_id}</div>
                            <div className="subline">unregistered source · {METHOD_LABEL[r.method]}</div>
                          </>
                        ) : (
                          <>
                            <div className="pri-name">{r.source_name}</div>
                            <div className="subline">
                              {r.source_id} · {METHOD_LABEL[r.method]}
                            </div>
                          </>
                        )}
                      </td>
                      <td className="id" title={r.received_at}>
                        {formatWhen(r.received_at)}
                      </td>
                      <td>
                        <StatusPill r={r} />
                      </td>
                      <td className="id">
                        {r.input_row_count !== null ? r.input_row_count.toLocaleString() : <span className="mut">—</span>}
                      </td>
                      <td className="id">
                        <CountCell value={r.accepted} kind="acc" />
                      </td>
                      <td className="id">
                        <CountCell value={r.quarantined} kind="qua" />
                      </td>
                      <td>
                        {r.file_name !== null ? (
                          <span className="id fname" title={r.file_name}>
                            {r.file_name}
                          </span>
                        ) : (
                          <span className="mut">—</span>
                        )}
                      </td>
                      <td className="chev" aria-hidden="true">
                        ›
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {/* Keyset pager: no total (a COUNT over the joined read is too costly, D124) — page
                position + a forward Next off next_cursor, Prev from the visited-cursor stack. */}
            <div className="pager">
              <span className="pageinfo">
                Page {pageIndex + 1} · showing {rows.length} run{rows.length === 1 ? '' : 's'}
              </span>
              <div className="pagebtns">
                <button type="button" className="btn sm" onClick={goPrev} disabled={pageIndex === 0}>
                  ← Prev
                </button>
                <button type="button" className="btn sm" onClick={goNext} disabled={nextCursor === null}>
                  Next →
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      <RunDetail run={selected} onClose={() => setSelected(null)} />
    </>
  )
}
