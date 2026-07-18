import { useQuery } from '@tanstack/react-query'

import type { AuthSnapshot } from '../../auth/AuthSnapshot'
import { getJson } from './client'
import { isRealMode } from './mode'

// Tenant Quarantine console (slice 15a, b8b85f4), tenant slice. Types mirror the real
// dis-ui-server contract EXACTLY (services/dis-ui-server/.../schemas/quarantine.py): the two
// reads are GET /api/v1/quarantine?source=&error_type=&status=&window= -> { items, open_count }
// (open_count is filter-INDEPENDENT) and GET /api/v1/quarantine/{item_id} where item_id is the
// type-tagged "row:<uuid>"/"chunk:<uuid>" handle returned by the list (round-tripped verbatim).
// Mode-aware (T10): real mode calls the live endpoints; fixture mode (default + tests) returns
// inlined items and applies the filters client-side so the screen works with no backend.
//
// Honest semantics (slice 15a): original_payload is DEFERRED -> ALWAYS null; status "resolved"
// returns nothing (no resolve path exists, D82); source == source_id (no registry); chain_depth
// is always 0 (no lineage). There is NO resolve/dismiss/resubmit action server-side.

// Wire vocabularies (mirrored 1:1 from the backend Literal types).
export type Kind = 'row' | 'chunk'
export type StatusWire = 'open' | 'resolved'
export type WindowWire = '24h' | '7d' | '30d'
export type StageWire = 'source-shape' | 'canonical-shape' | 'fk' | 'normalization' | 'other'

export type QuarantineListRow = {
  id: string // type-tagged "row:<uuid>"/"chunk:<uuid>" - opaque, round-tripped to detail
  kind: Kind
  tenant_id: string // Chunk 1: owning tenant (quarantine.*.tenant_id, NOT NULL)
  tenant_name?: string | null // Chunk 9: identity_mirror.tenants.name; absent (older backend)/null → UUID
  trace_id: string
  source_id: string // the filter key (Dashboard ?source= deep link)
  source: string // display name; == source_id today
  store_id: string | null // 52b: the held item's store (uuid str); null if unset/unmirrored
  store_name: string | null // 52b: resolved via the inline stores join; null when store_id null
  error_reason: string // a FailureCode member
  failure_stage: StageWire
  failed_at: string // ISO-8601
  status: StatusWire
}

export type QuarantineListResponse = {
  items: QuarantineListRow[]
  open_count: number // filter-INDEPENDENT (the header badge)
}

// One structured per-failure entry on the DETAIL (52b). Only check + reason are always present;
// EVERY other field is nullable (present-but-null on the wire, never absent) -> check with
// !== null, NEVER truthiness (row_index / transform_index can legitimately be 0). Additive: lives
// ALONGSIDE the unchanged flattened error_context string, never replacing it. (Field order mirrors
// the backend model, schemas/quarantine.py QuarantineFailure.)
export type QuarantineFailure = {
  check: string // the machine check name, e.g. "str_length(None, 128)"
  reason: string // human-readable failure line; the headline for thin structural failures
  column: string | null // canonical column; populated even on structural failures
  row_index: number | null // row offset; null for whole-batch (chunk) failures; CAN be 0
  value: string | null // the offending value; null for structural / where not captured
  source_column: string | null // the tenant's own source column; present for mapping-stage only
  expected_format: string | null // non-null for mapping-stage failures, null for Pandera
  transform_index: number | null // non-null for mapping-stage failures; CAN be 0
}

export type QuarantineDetail = {
  id: string
  kind: Kind
  trace_id: string
  source: string // NOTE: detail has source but NO source_id (the list carries source_id)
  store_id: string | null // 52b: the held item's store (uuid str); null if unset/unmirrored
  store_name: string | null // 52b: resolved via the inline stores join; null when store_id null
  failed_at: string
  mapping_version: number | null // the "v1" token; null for pre-lookup chunk failures
  error_reason: string
  failure_stage: StageWire
  error_context: string // the flat human summary (UNCHANGED; 52b keeps it alongside failures[])
  failures: QuarantineFailure[] // 52b: structured per-failure detail (detail only)
  original_payload: Record<string, unknown> | null // DEFERRED this slice -> always null
  chain_depth: number // always 0 (no lineage until Slice 12)
}

// The four server-side filters (all optional; absent = no constraint). Mirrors the query params.
export type QuarantineFilters = {
  source?: string
  errorType?: StageWire
  status?: StatusWire
  window?: WindowWire
}

// ---- Fixture data (local dev + tests). Two sources so the Source filter has options; all open
// (resolved yields nothing, matching the real endpoint). original_payload is always null. The
// failures[] arrays are engineered to exercise every 52b edge case the live data can't yet show
// (all current live rows are pre-52b, so their value/source_column/expected_format are all null):
// row 1 = MULTI-FAILURE thin structural (mirrors the live product_name + product_description case),
// row 2 = RICH mapping (value + source_column + expected_format + transform_index:0 + row_index:0,
// proving 0 survives a !== null check), chunk 3 = thin structural whole-batch + NULL store_name.

const FIXTURE_ROWS: QuarantineListRow[] = [
  {
    id: 'row:0190ac0e-1a01-7001-8a01-000000000001',
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000a1',
    kind: 'row',
    trace_id: '0190ac0e-1a01-7001-8a01-000000000001',
    source_id: 'manual_csv_upload',
    source: 'manual_csv_upload',
    store_id: 's_0190ac0e-1a01-7001-8a01-000000000010',
    store_name: 'Żabka W-002 Praga',
    error_reason: 'VALIDATION_ROW_FAILED',
    failure_stage: 'canonical-shape',
    failed_at: '2026-06-09T09:08:00Z',
    status: 'open',
  },
  {
    id: 'row:0190ac0e-1a01-7001-8a01-000000000002',
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000b2',
    kind: 'row',
    trace_id: '0190ac0e-1a01-7001-8a01-000000000002',
    source_id: 'manual_csv_upload',
    source: 'manual_csv_upload',
    store_id: 's_0190ac0e-1a01-7001-8a01-000000000011',
    store_name: 'Żabka K-114 Kraków',
    error_reason: 'MAPPING_EXECUTION_FAILED',
    failure_stage: 'normalization',
    failed_at: '2026-06-09T09:05:00Z',
    status: 'open',
  },
  {
    id: 'chunk:0190ac0e-1a01-7001-8a01-000000000003',
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000a1',
    kind: 'chunk',
    trace_id: '0190ac0e-1a01-7001-8a01-000000000003',
    source_id: 'shopify_pos_v2',
    source: 'shopify_pos_v2',
    store_id: null, // whole-batch failure held before store identity resolved
    store_name: null, // null store_name -> the list Store cell renders the honest em-dash
    error_reason: 'PRE_VALIDATION_FAILED',
    failure_stage: 'source-shape',
    failed_at: '2026-06-08T16:40:00Z',
    status: 'open',
  },
]

const FIXTURE_DETAILS: Record<string, QuarantineDetail> = {
  'row:0190ac0e-1a01-7001-8a01-000000000001': {
    id: 'row:0190ac0e-1a01-7001-8a01-000000000001',
    kind: 'row',
    trace_id: '0190ac0e-1a01-7001-8a01-000000000001',
    source: 'manual_csv_upload',
    store_id: 's_0190ac0e-1a01-7001-8a01-000000000010',
    store_name: 'Żabka W-002 Praga',
    failed_at: '2026-06-09T09:08:00Z',
    mapping_version: 1,
    error_reason: 'VALIDATION_ROW_FAILED',
    failure_stage: 'canonical-shape',
    error_context: 'canonical-shape: 2 columns failed str_length at row 17149',
    // MULTI-FAILURE, thin structural: two Pandera length failures at the same row (value and the
    // mapping-only fields all null). Mirrors the live product_name + product_description example.
    failures: [
      {
        check: 'str_length(None, 128)',
        reason: "column 'product_name' failed 'str_length(None, 128)' at row 17149",
        column: 'product_name',
        row_index: 17149,
        value: null,
        source_column: null,
        expected_format: null,
        transform_index: null,
      },
      {
        check: 'str_length(None, 128)',
        reason: "column 'product_description' failed 'str_length(None, 128)' at row 17149",
        column: 'product_description',
        row_index: 17149,
        value: null,
        source_column: null,
        expected_format: null,
        transform_index: null,
      },
    ],
    original_payload: null,
    chain_depth: 0,
  },
  'row:0190ac0e-1a01-7001-8a01-000000000002': {
    id: 'row:0190ac0e-1a01-7001-8a01-000000000002',
    kind: 'row',
    trace_id: '0190ac0e-1a01-7001-8a01-000000000002',
    source: 'manual_csv_upload',
    store_id: 's_0190ac0e-1a01-7001-8a01-000000000011',
    store_name: 'Żabka K-114 Kraków',
    failed_at: '2026-06-09T09:05:00Z',
    mapping_version: 1,
    error_reason: 'MAPPING_EXECUTION_FAILED',
    failure_stage: 'normalization',
    error_context: 'normalization: column sold_at unparseable (expected ISO-8601)',
    // RICH mapping-stage: value + source_column + expected_format present; transform_index:0 and
    // row_index:0 deliberately 0 to prove the !== null presence check keeps a 0 (truthiness drops).
    failures: [
      {
        check: 'parse_date(%Y-%m-%d)',
        reason: "column 'sold_at' failed 'parse_date' at row 0",
        column: 'sold_at',
        row_index: 0,
        value: '03-12-25',
        source_column: 'txn_date',
        expected_format: 'YYYY-MM-DD',
        transform_index: 0,
      },
    ],
    original_payload: null,
    chain_depth: 0,
  },
  'chunk:0190ac0e-1a01-7001-8a01-000000000003': {
    id: 'chunk:0190ac0e-1a01-7001-8a01-000000000003',
    kind: 'chunk',
    trace_id: '0190ac0e-1a01-7001-8a01-000000000003',
    source: 'shopify_pos_v2',
    store_id: null,
    store_name: null,
    failed_at: '2026-06-08T16:40:00Z',
    mapping_version: null, // pre-lookup chunk failure carries no mapping version
    error_reason: 'PRE_VALIDATION_FAILED',
    failure_stage: 'source-shape',
    error_context: 'source-shape: required column sku absent from payload',
    // Thin structural, WHOLE-BATCH: row_index null (no single offending row); Pandera-only fields.
    failures: [
      {
        check: 'column_in_schema(sku)',
        reason: "required column 'sku' absent from the uploaded file",
        column: 'sku',
        row_index: null,
        value: null,
        source_column: null,
        expected_format: null,
        transform_index: null,
      },
    ],
    original_payload: null,
    chain_depth: 0,
  },
}

const WINDOW_MS: Record<WindowWire, number> = {
  '24h': 24 * 60 * 60 * 1000,
  '7d': 7 * 24 * 60 * 60 * 1000,
  '30d': 30 * 24 * 60 * 60 * 1000,
}

// Fixture-mode filtering, mirroring the server's WHERE: source (source_id), error_type
// (failure_stage), status (open == the only producing state; resolved yields nothing), and the
// trailing time window. open_count is the count of open items, INDEPENDENT of the filters.
function fixtureList(filters: QuarantineFilters): QuarantineListResponse {
  const now = Date.now()
  const items = FIXTURE_ROWS.filter(
    (r) =>
      (filters.source === undefined || r.source_id === filters.source) &&
      (filters.errorType === undefined || r.failure_stage === filters.errorType) &&
      (filters.status === undefined || r.status === filters.status) &&
      (filters.window === undefined ||
        now - new Date(r.failed_at).getTime() <= WINDOW_MS[filters.window]),
  )
  return { items, open_count: FIXTURE_ROWS.filter((r) => r.status === 'open').length }
}

function buildQuery(filters: QuarantineFilters): string {
  const params = new URLSearchParams()
  if (filters.source !== undefined) params.set('source', filters.source)
  if (filters.errorType !== undefined) params.set('error_type', filters.errorType)
  if (filters.status !== undefined) params.set('status', filters.status)
  if (filters.window !== undefined) params.set('window', filters.window)
  const q = params.toString()
  return q.length > 0 ? `?${q}` : ''
}

// GET /api/v1/quarantine. Tenant-scoped server-side (token tenant only).
export async function getQuarantineList(
  filters: QuarantineFilters,
): Promise<QuarantineListResponse> {
  if (isRealMode()) {
    return getJson<QuarantineListResponse>(`/api/v1/quarantine${buildQuery(filters)}`)
  }
  return fixtureList(filters)
}

// GET /api/v1/quarantine/{item_id}. item_id is the type-tagged handle from the list row, sent
// verbatim (getting the "row:"/"chunk:" prefix wrong breaks detail dispatch server-side).
export async function getQuarantineDetail(itemId: string): Promise<QuarantineDetail> {
  if (isRealMode()) {
    return getJson<QuarantineDetail>(`/api/v1/quarantine/${encodeURIComponent(itemId)}`)
  }
  const detail = FIXTURE_DETAILS[itemId]
  if (detail === undefined) {
    throw new Error(`no fixture quarantine detail for item id ${itemId}`)
  }
  return detail
}

export function useQuarantineList(snapshot: AuthSnapshot | null, filters: QuarantineFilters) {
  return useQuery({
    queryKey: [
      'dis-ui-server',
      'quarantine',
      'list',
      snapshot?.tenantId ?? 'none',
      filters.source ?? 'all',
      filters.errorType ?? 'all',
      filters.status ?? 'all',
      filters.window ?? 'all',
    ],
    queryFn: () => getQuarantineList(filters),
    enabled: snapshot !== null,
    staleTime: Infinity,
    retry: false,
  })
}

export function useQuarantineDetail(snapshot: AuthSnapshot | null, itemId: string | null) {
  return useQuery({
    queryKey: ['dis-ui-server', 'quarantine', 'detail', itemId ?? 'none'],
    queryFn: () => getQuarantineDetail(itemId as string),
    enabled: snapshot !== null && itemId !== null,
    staleTime: Infinity,
    retry: false,
  })
}
