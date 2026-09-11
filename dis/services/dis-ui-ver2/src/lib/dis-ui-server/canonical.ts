import { useQuery } from '@tanstack/react-query'

import type { AuthSnapshot } from '../../auth/AuthSnapshot'
import { getJson } from './client'
import { isRealMode } from './mode'

// Canonical Data Explorer (tenant slice). Shaped EXACTLY to the real dis-ui-server contract
// (services/dis-ui-server/.../schemas/canonical.py: StoreSkuPositionListResponse /
// StoreSkuPositionRow): GET /api/v1/canonical/store-sku-positions, a bounded newest-first sample
// of canonical.store_sku_current_position (READ-ONLY; canonical already in the BFF read-set),
// tenant-scoped (RLS two-GUC). Mode-aware: real mode calls the live endpoint; fixture mode
// (default + tests) returns plausible inlined rows so local dev needs no backend.
//
// The list row IS the full record — there is NO separate detail endpoint; the drawer renders from
// the row already in hand. Money / quantity / rate fields are STRINGS on the wire (NUMERIC,
// money-safe — no float rounding); the UI trims trailing zeros cosmetically only. store_name is
// the friendly store label (52a). attribute_staleness_map maps a DYNAMIC SUBSET of field names ->
// the ISO timestamp that field's value was last confirmed/sourced (a per-field trust signal, woven
// beside each value in the drawer, never a raw JSON blob).

export type StoreSkuPositionRow = {
  id: string
  store_id: string // tenant-scoped store FK (UUID); friendly label is store_name
  store_name: string | null // identity_mirror.stores.name; nullable in schema, populated in practice
  sku_id: string // SKU — primary lookup key
  sku_variant: string | null
  sku_lot_batch: string | null
  barcode: string | null
  product_name: string // human recognition; leads the list
  product_description: string | null
  product_category: string | null // RAW ingested CSV code (any string, e.g. "9103") — never humanize
  product_sub_category: string | null
  product_department: string | null
  supplier_id: string | null
  packaging_type: string | null
  sku_size: string | null // NUMERIC string
  unit_of_measure: string | null // e.g. "PZ"
  current_retail_price: string | null // NUMERIC string (money-safe); null when unpriced
  unit_cost: string | null // NUMERIC string
  promo_price: string | null // NUMERIC string
  promo_identifier: string | null
  yesterday_retail_price: string | null // NUMERIC string
  tax_treatment: string | null
  stock_qty: string | null // NUMERIC string; null when unset
  lead_time_days: number | null
  expiry_date: string | null // date-only when present
  receipt_date: string | null // date-only when present
  expiry_source: string | null
  expiry_confidence: string | null // 0–1 NUMERIC string, rendered as a %
  regulatory_flag: boolean // populated (false in current data)
  regulatory_type: string | null
  currency: string // ISO code for money rendering (e.g. "PLN") — never hardcode
  reorder_point: string | null // NUMERIC string
  sku_status: string | null
  velocity_7day: string | null // NUMERIC string
  stock_age_days: number | null
  unit_cost_trend_30day: string | null // NUMERIC string
  attribute_staleness_map: Record<string, string> | null // field name -> ISO confirm stamp (subset)
  current_retail_price_changed_at: string | null
  product_name_changed_at: string | null
  last_source_event_at: string | null // observed at
  mapping_version: number // shown as v{n}; no raw mapping_version_id key served
  trace_id: string // lineage anchor
  dis_channel: string | null // ingress channel, e.g. "csv-upload"
  last_updated_at: string // written at / Updated
}

export type StoreSkuPositionListResponse = {
  items: StoreSkuPositionRow[]
}

// The endpoint's optional filters (store id + sku contains-search).
export type CanonicalFilters = {
  store?: string
  sku?: string
}

// Plausible fixture shaped to StoreSkuPositionRow (newest first), using live-capture PLN retail
// values. Numbers are illustrative, not fabricated truth: fixture mode is local-dev/test only; real
// mode reads the live endpoint. Prices/quantities/rates are strings exactly as the wire carries
// them. Freshness stamps are computed RELATIVE to load time (isoAgo) so the pill colors
// (fresh/aging/stale) stay stable in dev and tests without pinning the clock; real mode uses the
// live stamps as-is. The three rows exercise: a fully-populated row (all three pill colors + a
// tracked-but-null field), a mostly-null row mirroring current smoke data (fresh-only map), and a
// row with an empty map (no woven pills).
const FIXTURE_STORE = '019e4b9e-7567-7857-9f83-025737c833c1'
const DAY_MS = 86_400_000
const NOW_MS = Date.now()
function isoAgo(days: number): string {
  return new Date(NOW_MS - days * DAY_MS).toISOString()
}

const FIXTURE_POSITIONS: StoreSkuPositionRow[] = [
  {
    id: '019f5bca-6783-7a02-9a7c-e7970f0c536d',
    store_id: FIXTURE_STORE,
    store_name: 'Żabka Warszawa Centralna',
    sku_id: 'PU0025',
    sku_variant: null,
    sku_lot_batch: null,
    barcode: '8004698402214',
    product_name: 'PUPA Expo Mascara + Lash Duo',
    product_description: 'Volumising mascara and lash serum duo',
    product_category: '5401', // raw ingested CSV code, rendered as-is
    product_sub_category: 'Eye Makeup',
    product_department: 'Beauty',
    supplier_id: 'SUP-PUPA-IT',
    packaging_type: 'Carton',
    sku_size: '12.000',
    unit_of_measure: 'PZ',
    current_retail_price: '6.9000',
    unit_cost: '3.2000',
    promo_price: '5.9000',
    promo_identifier: 'SUMMER25',
    yesterday_retail_price: '6.9000',
    tax_treatment: 'STANDARD',
    stock_qty: null, // tracked-but-null: value null yet present in the staleness map below
    lead_time_days: 7,
    expiry_date: '2027-01-31',
    receipt_date: '2026-06-01',
    expiry_source: 'SUPPLIER_FEED',
    expiry_confidence: '0.95',
    regulatory_flag: false,
    regulatory_type: null,
    currency: 'PLN',
    reorder_point: '24.000',
    sku_status: 'ACTIVE',
    velocity_7day: '3.4000',
    stock_age_days: 41,
    unit_cost_trend_30day: '0.0002',
    attribute_staleness_map: {
      current_retail_price: isoAgo(0.2), // fresh (green, <= 1 day)
      unit_cost: isoAgo(2.5), // aging (amber, 2–3 days)
      promo_price: isoAgo(5), // stale (red, > 3 days)
      stock_qty: isoAgo(0.5), // tracked-but-null: stamp present, value null
      product_name: isoAgo(0.2), // fresh
    },
    current_retail_price_changed_at: isoAgo(0.2),
    product_name_changed_at: isoAgo(13),
    last_source_event_at: isoAgo(0.2),
    mapping_version: 3,
    trace_id: '019f5bca-4d01-7403-b039-304bd8e44075',
    dis_channel: 'csv-upload',
    last_updated_at: isoAgo(0.1),
  },
  {
    id: '019f5bca-7001-7abc-8811-aa1122334455',
    store_id: FIXTURE_STORE,
    store_name: 'Żabka Warszawa Centralna',
    sku_id: 'MAY2205',
    sku_variant: null,
    sku_lot_batch: null,
    barcode: '5900512340118',
    product_name: 'Maybelline Sky High Mascara Black',
    product_description: null,
    product_category: '9103', // raw ingested CSV code, rendered as-is
    product_sub_category: null,
    product_department: null,
    supplier_id: 'SUP-MAYB-PL',
    packaging_type: null,
    sku_size: null,
    unit_of_measure: 'PZ',
    current_retail_price: '0.0100',
    unit_cost: '0.0060',
    promo_price: null,
    promo_identifier: null,
    yesterday_retail_price: null,
    tax_treatment: 'STANDARD',
    stock_qty: null,
    lead_time_days: null,
    expiry_date: null,
    receipt_date: null,
    expiry_source: null,
    expiry_confidence: null,
    regulatory_flag: false,
    regulatory_type: null,
    currency: 'PLN',
    reorder_point: null,
    sku_status: null,
    velocity_7day: null,
    stock_age_days: null,
    unit_cost_trend_30day: null,
    attribute_staleness_map: {
      unit_cost: isoAgo(0.1), // fresh — mirrors live (only unit_cost + retail carry a stamp today)
      current_retail_price: isoAgo(0.1), // fresh
    },
    current_retail_price_changed_at: isoAgo(0.1),
    product_name_changed_at: isoAgo(57),
    last_source_event_at: isoAgo(0.1),
    mapping_version: 3,
    trace_id: '019f5bca-9d21-7b03-c039-1a2b3c4d5e6f',
    dis_channel: 'csv-upload',
    last_updated_at: isoAgo(0.05),
  },
  {
    id: '019f5bca-8112-7c0d-9e2f-bb2233445566',
    store_id: FIXTURE_STORE,
    store_name: 'Żabka Warszawa Centralna',
    sku_id: '928',
    sku_variant: '6-pack',
    sku_lot_batch: 'L2026-114',
    barcode: '5901234500289',
    product_name: 'Żabka Woda Źródlana 0.5L',
    product_description: null,
    product_category: '2081', // raw ingested CSV code, rendered as-is
    product_sub_category: 'Water',
    product_department: 'Grocery',
    supplier_id: 'SUP-ZAB-WAT',
    packaging_type: 'Shrink',
    sku_size: '0.500',
    unit_of_measure: 'L',
    current_retail_price: '0.9900',
    unit_cost: '0.3100',
    promo_price: null,
    promo_identifier: null,
    yesterday_retail_price: '0.9900',
    tax_treatment: 'REDUCED',
    stock_qty: '860.000',
    lead_time_days: 2,
    expiry_date: '2026-08-15',
    receipt_date: '2026-07-12',
    expiry_source: 'CALCULATED',
    expiry_confidence: '0.60',
    regulatory_flag: false,
    regulatory_type: null,
    currency: 'PLN',
    reorder_point: '200.000',
    sku_status: 'ACTIVE',
    velocity_7day: '310.0000',
    stock_age_days: 2,
    unit_cost_trend_30day: '0.0000',
    attribute_staleness_map: {}, // empty — no woven pills
    current_retail_price_changed_at: isoAgo(25),
    product_name_changed_at: isoAgo(186),
    last_source_event_at: isoAgo(1),
    mapping_version: 3,
    trace_id: '019f5bca-af31-7c04-d139-2b3c4d5e6f70',
    dis_channel: 'api',
    last_updated_at: isoAgo(1),
  },
]

// Build the query string from the optional filters (mirrors the other clients' buildQuery).
function buildQuery(filters: CanonicalFilters): string {
  const params = new URLSearchParams()
  if (filters.store !== undefined && filters.store !== '') params.set('store', filters.store)
  if (filters.sku !== undefined && filters.sku !== '') params.set('sku', filters.sku)
  const qs = params.toString()
  return qs === '' ? '' : `?${qs}`
}

// Fixture-mode filtering: store + sku applied deterministically (contains-search on sku_id).
function applyFixtureFilters(
  rows: StoreSkuPositionRow[],
  filters: CanonicalFilters,
): StoreSkuPositionRow[] {
  return rows.filter((r) => {
    if (filters.store !== undefined && filters.store !== '' && r.store_id !== filters.store) return false
    if (filters.sku !== undefined && filters.sku !== '') {
      return r.sku_id.toLowerCase().includes(filters.sku.toLowerCase())
    }
    return true
  })
}

// GET /api/v1/canonical/store-sku-positions. Tenant-scoped server-side. Real mode calls the live
// endpoint; fixture mode returns the inlined rows.
export async function getPositions(
  filters: CanonicalFilters = {},
): Promise<StoreSkuPositionListResponse> {
  if (isRealMode()) {
    return getJson<StoreSkuPositionListResponse>(
      `/api/v1/canonical/store-sku-positions${buildQuery(filters)}`,
    )
  }
  return { items: applyFixtureFilters(FIXTURE_POSITIONS, filters) }
}

export function usePositions(snapshot: AuthSnapshot | null, filters: CanonicalFilters = {}) {
  return useQuery({
    queryKey: [
      'dis-ui-server',
      'canonical',
      'positions',
      snapshot?.tenantId ?? 'none',
      filters.store ?? null,
      filters.sku ?? null,
    ],
    queryFn: () => getPositions(filters),
    enabled: snapshot !== null,
    staleTime: Infinity,
    retry: false,
  })
}
