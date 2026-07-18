import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { isOps } from '../auth/AuthSnapshot'
import { useAuth } from '../auth/useAuth'
import { ErrorState } from '../components/states/ErrorState'
import { LoadingState } from '../components/states/LoadingState'
import type { StoreSkuPositionRow } from '../lib/dis-ui-server/canonical'
import { usePositions } from '../lib/dis-ui-server/canonical'
import { useStoresOnboarded } from '../lib/dis-ui-server/stores'

// Canonical Data Explorer — the full served record (~44 fields, 52a) over GET
// /api/v1/canonical/store-sku-positions (READ-ONLY canonical, RLS two-GUC). The list (11 columns)
// serves find & orient; a row click opens the detail drawer that serves inspect & trust — the full
// grouped record with per-field freshness woven beside each value from attribute_staleness_map.
// There is NO separate detail endpoint: the list row IS the full record, so the drawer renders from
// the row already in hand (no second fetch). Reskinned to v2 tokens/glyphs, no icon lib.
//
// Honest nulls: many fields are null in current smoke data and render `—` (never a false 0) — they
// are real contract fields that light up when production data flows. store_name shows the friendly
// store label (never the store_id UUID); product_category is a RAW ingested code, rendered as-is.

const DAY_MS = 86_400_000

// --- freshness helpers (map-driven; used only for fields carrying a staleness stamp) ---
function daysAgo(iso: string): number {
  return Math.floor((Date.now() - new Date(iso).getTime()) / DAY_MS)
}

function ageClass(days: number): 'fresh' | 'aging' | 'stale' {
  if (days <= 1) return 'fresh'
  if (days <= 3) return 'aging'
  return 'stale'
}

function relAge(iso: string): string {
  const d = daysAgo(iso)
  if (d <= 0) return 'today'
  if (d === 1) return 'yesterday'
  return `${d} days ago`
}

// Short date-time, e.g. `14 Jul, 18:54`; honest `—` for null.
function formatWhen(value: string | null): string {
  if (value === null) return '—'
  const dt = new Date(value)
  const date = dt.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
  const time = dt.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  return `${date}, ${time}`
}

// Trailing-zero trim is display-only (the wire value stays a money-safe string).
function trimZeros(value: string): string {
  return value.replace(/0+$/, '').replace(/\.$/, '.00')
}

// Honest-null render helpers (typed, strict === null — not a loose `v == null` generic).
function orDash(value: string | null): ReactNode {
  return value === null ? <span className="mut">—</span> : value
}

function monoOrDash(value: string | null): ReactNode {
  return value === null ? <span className="mut">—</span> : <span className="mono">{value}</span>
}

// Money: trailing-zero-trimmed number + faint ISO currency suffix (e.g. `0.01 PLN`); `—` when null.
function Money({ value, currency }: { value: string | null; currency: string }): ReactNode {
  if (value === null) return <span className="mut">—</span>
  return (
    <>
      <span className="mono">{trimZeros(value)}</span> <span className="mut">{currency}</span>
    </>
  )
}

// Quantity: locale-grouped number + faint unit-of-measure suffix (e.g. `128 PZ`); `—` when null.
function Qty({ value, uom }: { value: string | null; uom: string | null }): ReactNode {
  if (value === null) return <span className="mut">—</span>
  return (
    <>
      <span className="mono">{Number(value).toLocaleString()}</span>
      {uom !== null ? <span className="mut"> {uom}</span> : null}
    </>
  )
}

// Generic woven-freshness helper (the novel element). Renders `children` and, IFF `field` is a key
// in the row's attribute_staleness_map, appends a colored age pill + the exact stamp beside it.
// Driven ENTIRELY off the map keys (a dynamic subset, up to ~10) — a field absent from the map
// renders plain (no pill). A tracked-but-null field still shows the pill because the caller passes
// the `—` node as children (null value != no freshness record).
function FieldValue({
  row,
  field,
  children,
}: {
  row: StoreSkuPositionRow
  field: string
  children: ReactNode
}): ReactNode {
  const stamp = row.attribute_staleness_map?.[field] ?? null
  if (stamp === null) return <>{children}</>
  const cls = ageClass(daysAgo(stamp))
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      {children}
      <span>
        <span className={`agepill ${cls}`}>confirmed {relAge(stamp)}</span>{' '}
        <span className="stamp">({formatWhen(stamp)})</span>
      </span>
    </span>
  )
}

// A dt/dd pair for the drawer's grouped record. Pass `row` + `field` to weave freshness off the
// staleness map; omit them for fields that never carry a stamp (lineage timestamps, ids).
function KV({
  label,
  row,
  field,
  children,
}: {
  label: string
  row?: StoreSkuPositionRow
  field?: string
  children: ReactNode
}): ReactNode {
  const body =
    row !== undefined && field !== undefined ? (
      <FieldValue row={row} field={field}>
        {children}
      </FieldValue>
    ) : (
      children
    )
  return (
    <>
      <dt>{label}</dt>
      <dd>{body}</dd>
    </>
  )
}

// The row-click drawer: the full canonical record, grouped, with per-field freshness woven in. No
// fetch — it renders the row already in hand (the list row IS the full record).
function RecordDrawer({ row, onClose }: { row: StoreSkuPositionRow | null; onClose: () => void }) {
  const open = row !== null
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

  return (
    <>
      <div className={open ? 'drawer-scrim on' : 'drawer-scrim'} onClick={onClose} />
      <div
        className={open ? 'drawer on' : 'drawer'}
        role="dialog"
        aria-modal="true"
        aria-hidden={!open}
        aria-label="Canonical record detail"
        tabIndex={-1}
        ref={panelRef}
      >
        {row !== null ? (
          <>
            <div className="dhd">
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="sub mono" style={{ marginBottom: 8 }}>
                  {row.sku_id} · canonical.store_sku_current_position
                </div>
                <h3>{row.product_name}</h3>
                <div className="sub" style={{ marginTop: 6 }}>
                  {row.store_name ?? '—'} · {row.product_category ?? '—'} · mapping v
                  {row.mapping_version}
                </div>
              </div>
              <button className="iconbtn" onClick={onClose} aria-label="Close detail">
                ×
              </button>
            </div>

            <div className="dbd">
              <div className="detsec">
                <h4>Identity</h4>
                <dl className="kv">
                  <KV label="SKU">
                    <span className="mono">{row.sku_id}</span>
                  </KV>
                  <KV label="Variant" row={row} field="sku_variant">
                    {orDash(row.sku_variant)}
                  </KV>
                  <KV label="Lot / batch" row={row} field="sku_lot_batch">
                    {orDash(row.sku_lot_batch)}
                  </KV>
                  <KV label="Barcode" row={row} field="barcode">
                    {monoOrDash(row.barcode)}
                  </KV>
                  <KV label="Store">{orDash(row.store_name)}</KV>
                </dl>
              </div>

              <div className="detsec">
                <h4>Product</h4>
                <dl className="kv">
                  <KV label="Name" row={row} field="product_name">
                    {row.product_name}
                  </KV>
                  <KV label="Description" row={row} field="product_description">
                    {orDash(row.product_description)}
                  </KV>
                  <KV label="Category" row={row} field="product_category">
                    {orDash(row.product_category)}
                  </KV>
                  <KV label="Sub-category" row={row} field="product_sub_category">
                    {orDash(row.product_sub_category)}
                  </KV>
                  <KV label="Department" row={row} field="product_department">
                    {orDash(row.product_department)}
                  </KV>
                  <KV label="Supplier" row={row} field="supplier_id">
                    {orDash(row.supplier_id)}
                  </KV>
                  <KV label="Packaging" row={row} field="packaging_type">
                    {orDash(row.packaging_type)}
                  </KV>
                  <KV label="Size" row={row} field="sku_size">
                    {row.sku_size === null ? (
                      <span className="mut">—</span>
                    ) : (
                      <>
                        {row.sku_size}
                        {row.unit_of_measure !== null ? ` ${row.unit_of_measure}` : ''}
                      </>
                    )}
                  </KV>
                </dl>
              </div>

              <div className="detsec">
                <h4>Pricing</h4>
                <dl className="kv">
                  <KV label="Retail price" row={row} field="current_retail_price">
                    <Money value={row.current_retail_price} currency={row.currency} />
                  </KV>
                  <KV label="Yesterday" row={row} field="yesterday_retail_price">
                    <Money value={row.yesterday_retail_price} currency={row.currency} />
                  </KV>
                  <KV label="Unit cost" row={row} field="unit_cost">
                    <Money value={row.unit_cost} currency={row.currency} />
                  </KV>
                  <KV label="Promo" row={row} field="promo_price">
                    {row.promo_price === null ? (
                      <span className="mut">—</span>
                    ) : (
                      <>
                        <Money value={row.promo_price} currency={row.currency} />
                        {row.promo_identifier !== null ? (
                          <span className="mut"> ({row.promo_identifier})</span>
                        ) : null}
                      </>
                    )}
                  </KV>
                  <KV label="Cost trend 30d" row={row} field="unit_cost_trend_30day">
                    {orDash(row.unit_cost_trend_30day)}
                  </KV>
                  <KV label="Tax" row={row} field="tax_treatment">
                    {orDash(row.tax_treatment)}
                  </KV>
                  <KV label="Currency">{row.currency}</KV>
                </dl>
              </div>

              <div className="detsec">
                <h4>Stock &amp; inventory</h4>
                <dl className="kv">
                  <KV label="Stock qty" row={row} field="stock_qty">
                    <Qty value={row.stock_qty} uom={row.unit_of_measure} />
                  </KV>
                  <KV label="Velocity 7d" row={row} field="velocity_7day">
                    {row.velocity_7day === null ? (
                      <span className="mut">—</span>
                    ) : (
                      Number(row.velocity_7day).toLocaleString()
                    )}
                  </KV>
                  <KV label="Reorder point" row={row} field="reorder_point">
                    {orDash(row.reorder_point)}
                  </KV>
                  <KV label="Lead time">
                    {row.lead_time_days === null ? (
                      <span className="mut">—</span>
                    ) : (
                      `${row.lead_time_days} days`
                    )}
                  </KV>
                  <KV label="Stock age">
                    {row.stock_age_days === null ? (
                      <span className="mut">—</span>
                    ) : (
                      `${row.stock_age_days} days`
                    )}
                  </KV>
                </dl>
              </div>

              <div className="detsec">
                <h4>Expiry &amp; compliance</h4>
                <dl className="kv">
                  <KV label="Expiry date" row={row} field="expiry_date">
                    {orDash(row.expiry_date)}
                  </KV>
                  <KV label="Receipt date" row={row} field="receipt_date">
                    {orDash(row.receipt_date)}
                  </KV>
                  <KV label="Expiry source" row={row} field="expiry_source">
                    {orDash(row.expiry_source)}
                  </KV>
                  <KV label="Expiry confidence">
                    {row.expiry_confidence === null ? (
                      <span className="mut">—</span>
                    ) : (
                      `${Math.round(Number(row.expiry_confidence) * 100)}%`
                    )}
                  </KV>
                  <KV label="Regulatory">
                    {row.regulatory_flag
                      ? `Yes${row.regulatory_type !== null ? ` · ${row.regulatory_type}` : ''}`
                      : 'No'}
                  </KV>
                  <KV label="SKU status" row={row} field="sku_status">
                    {orDash(row.sku_status)}
                  </KV>
                </dl>
              </div>

              <div className="detsec">
                <h4>Freshness &amp; lineage</h4>
                <dl className="kv">
                  <KV label="Last updated">{formatWhen(row.last_updated_at)}</KV>
                  <KV label="Last source event">{formatWhen(row.last_source_event_at)}</KV>
                  <KV label="Price changed">{formatWhen(row.current_retail_price_changed_at)}</KV>
                  <KV label="Name changed">{formatWhen(row.product_name_changed_at)}</KV>
                  <KV label="Mapping version">v{row.mapping_version}</KV>
                  <KV label="Channel">{orDash(row.dis_channel)}</KV>
                  <KV label="Trace">{monoOrDash(row.trace_id)}</KV>
                  <KV label="Record id">
                    <span className="mono">{row.id}</span>
                  </KV>
                </dl>
              </div>

              {/* Woven-freshness legend: the three pill colors (age of the confirmation stamp). */}
              <div
                style={{
                  marginTop: 22,
                  display: 'flex',
                  gap: 14,
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  fontSize: 12,
                  color: 'var(--text-2)',
                }}
              >
                <span>Freshness:</span>
                <span className="agepill fresh">≤ 1 day</span>
                <span className="agepill aging">2–3 days</span>
                <span className="agepill stale">&gt; 3 days</span>
              </div>
            </div>
          </>
        ) : null}
      </div>
    </>
  )
}

export function CanonicalExplorer() {
  const { snapshot } = useAuth()
  const [skuInput, setSkuInput] = useState('')
  const [sku, setSku] = useState('')
  const [store, setStore] = useState('')
  const [selected, setSelected] = useState<StoreSkuPositionRow | null>(null)

  const q = usePositions(snapshot, { sku: sku || undefined, store: store || undefined })
  // NOTE: the row list below is still capped at the newest 50 by last_updated_at (backend
  // _POSITIONS_LIMIT=50, no cursor pagination yet — a separate backend concern). This fix is ONLY
  // about where the STORE FILTER gets its options; the fetch/limit is unchanged.
  const rows: StoreSkuPositionRow[] = q.data?.items ?? []

  const platform = snapshot !== null && isOps(snapshot)

  // Store-filter options are sourced from the ONBOARDED-STORES ROSTER, not the recency-capped data
  // page. GET /api/v1/stores-onboarded is tenant-scoped (require_tenant), so it 403s for a PLATFORM
  // token — there is NO cross-tenant roster endpoint. So:
  //  - TENANT: fetch the roster (all the tenant's onboarded stores) and build options from it. Every
  //    onboarded store appears in the filter even if it has zero canonical rows yet — this is the
  //    fix (the old data-page derivation silently hid stores whose rows sat beyond the 50-row cap).
  //  - PLATFORM: no roster is available, so fall back to the distinct stores in the loaded page.
  //    This retains the cap limitation for PLATFORM until a cross-tenant roster endpoint exists.
  // The option VALUE is always the store_id (UUID) — the canonical ?store= param is a store_id.
  const rosterQ = useStoresOnboarded(platform ? null : snapshot)
  const storeOptions = useMemo<{ id: string; label: string }[]>(() => {
    if (platform) {
      const byId = new Map<string, string | null>()
      for (const r of q.data?.items ?? []) {
        if (!byId.has(r.store_id)) byId.set(r.store_id, r.store_name)
      }
      return Array.from(byId, ([id, name]) => ({ id, label: name ?? `${id.slice(0, 8)}…` }))
    }
    // TENANT: roster-sourced. Label = name + code (as the Upload store picker does), code omitted
    // when null. Names always come from the roster, so real store names show even before rows load.
    return (rosterQ.data ?? []).map((s) => ({
      id: s.store_id,
      label: s.store_code !== null ? `${s.name} (${s.store_code})` : s.name,
    }))
  }, [platform, q.data, rosterQ.data])

  // The label of the currently-selected store (for the honest per-store empty state).
  const selectedStoreLabel = storeOptions.find((s) => s.id === store)?.label ?? null

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Canonical Data Explorer</h1>
          <div className="sub">
            Inspect normalized records and trace each value back to its source and mapping version.
          </div>
        </div>
      </div>

      <div className="toolbar">
        <form
          className="search"
          onSubmit={(e) => {
            e.preventDefault()
            setSku(skuInput.trim())
          }}
        >
          <span aria-hidden>⌕</span>
          <input
            aria-label="Search SKU"
            placeholder="Search by SKU"
            value={skuInput}
            onChange={(e) => setSkuInput(e.target.value)}
          />
        </form>
        <label className="filter">
          Store{' '}
          <select aria-label="Store" value={store} onChange={(e) => setStore(e.target.value)}>
            <option value="">All</option>
            {storeOptions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label className="filter">
          Entity{' '}
          <select aria-label="Entity" defaultValue="stock_position">
            <option value="stock_position">Stock position</option>
            <option value="sale_events" disabled>
              Sale events (soon)
            </option>
            <option value="change_events" disabled>
              Change events (soon)
            </option>
          </select>
        </label>
      </div>

      <div className="card">
        <div className="hd">
          <h3>Stock position</h3>
          <span className="badge b-mut">{rows.length}</span>
        </div>
        {q.isPending ? (
          <LoadingState label="Loading canonical records…" />
        ) : q.isError ? (
          <ErrorState message="Could not load canonical records." />
        ) : rows.length === 0 ? (
          <div className="bd">
            <div className="empty">
              {store !== '' ? (
                // Honest per-store empty state: an onboarded store with no canonical rows yet is a
                // CORRECT result (never ingested), not an error and not a reason to hide the store.
                <>
                  <h4>No canonical data for this store yet</h4>
                  <div>
                    {selectedStoreLabel ?? 'This store'} is onboarded but has no canonical records
                    yet. They appear here once data has been ingested for it.
                  </div>
                </>
              ) : (
                <>
                  <h4>No canonical records</h4>
                  <div>No positions match the current filters.</div>
                </>
              )}
            </div>
          </div>
        ) : (
          <>
            <div style={{ overflow: 'auto' }}>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>SKU</th>
                    <th className="cx-product">Product</th>
                    <th className="cx-store">Store</th>
                    <th>Retail price</th>
                    <th>Stock qty</th>
                    <th>Promo price</th>
                    <th>Updated</th>
                    <th>Price changed</th>
                    <th>Velocity 7d</th>
                    <th>Stock age</th>
                    <th>Category</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
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
                      <td className="id" title={r.product_name}>
                        {r.sku_id}
                      </td>
                      <td className="pri-name cx-product">{r.product_name}</td>
                      <td className="cx-store">{orDash(r.store_name)}</td>
                      <td>
                        <Money value={r.current_retail_price} currency={r.currency} />
                      </td>
                      <td>
                        <Qty value={r.stock_qty} uom={r.unit_of_measure} />
                      </td>
                      <td>
                        <Money value={r.promo_price} currency={r.currency} />
                      </td>
                      <td className="id" title={r.last_updated_at}>
                        {formatWhen(r.last_updated_at)}
                      </td>
                      <td className="id" title={r.current_retail_price_changed_at ?? ''}>
                        {formatWhen(r.current_retail_price_changed_at)}
                      </td>
                      <td className="mono">
                        {r.velocity_7day === null ? (
                          <span className="mut">—</span>
                        ) : (
                          Number(r.velocity_7day).toLocaleString()
                        )}
                      </td>
                      <td className="mono">
                        {r.stock_age_days === null ? (
                          <span className="mut">—</span>
                        ) : (
                          `${r.stock_age_days}d`
                        )}
                      </td>
                      <td>{orDash(r.product_category)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="bd" style={{ color: 'var(--text-3)', fontSize: 12 }}>
              Bounded sample (newest {rows.length}). Click any record for its full canonical detail
              with per-field freshness.
            </div>
          </>
        )}
      </div>

      <RecordDrawer row={selected} onClose={() => setSelected(null)} />
    </>
  )
}
