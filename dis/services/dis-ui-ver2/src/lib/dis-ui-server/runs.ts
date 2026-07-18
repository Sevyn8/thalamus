import { useQuery } from '@tanstack/react-query'

import type { AuthSnapshot } from '../../auth/AuthSnapshot'
import { getJson } from './client'
import { isRealMode } from './mode'

// Ingestion Runs (tenant slice). Shaped EXACTLY to Sanjeev's rebuilt dis-ui-server contract
// (services/dis-ui-server/.../schemas/runs.py: RunListResponse / RunRow, D117-D125): GET
// /api/v1/runs, one tenant-scoped read over bronze.data_ingress_events (READ-ONLY, D111; RLS
// two-GUC, D91) with the run VERDICT + counts DERIVED from audit.events (D117-D119), one row per
// ingress execution, newest-first, KEYSET-paginated (D124). Mode-aware: real mode calls the live
// endpoint; fixture mode (default + tests) returns plausible inlined rows so local dev needs no
// backend.
//
// HONEST NULLS — the backend returns these absent (never fabricated) and the UI renders them as
// such (per-column "—"/deferred labels; D119 criteria 3/5):
//   - store_name / source_name / template_name / template_id / file_name / mapping_version /
//     published_at / completed_at are null where they cannot resolve (store deferred, source has
//     no registry row, run predates templates, upload carried no filename, run not terminal).
//   - accepted / quarantined are null unless the run reached the matching terminal audit event;
//     input_row_count is the worker's DuckDB preflight total. The wire does NOT assert
//     accepted + quarantined == input_row_count (two independent parsers, D119) — the UI computes
//     the reconcile line honestly and represents a gap rather than forcing agreement.
//   - status is only the 4 real verdicts (processing/succeeded/quarantined/failed).

export type StatusWire = 'processing' | 'succeeded' | 'quarantined' | 'failed'
export type MethodWire = 'csv_upload' | 'api' | 'csv_erp' | 'reverse_api'
export type WindowWire = '24h' | '7d' | '30d'

// One ingress run — field-for-field the rebuilt wire shape (schemas/runs.py:RunRow, 20 fields).
// PII / payload-location columns (auth_principal, client_ip, user_agent, gcs_uri) are omitted
// server-side, so not here.
export type RunRow = {
  id: string
  trace_id: string
  tenant_id: string // Chunk 1: owning tenant (bronze.tenant_id, NOT NULL) — fleet attribution
  tenant_name?: string | null // Chunk 9: identity_mirror.tenants.name; absent (older backend)/null → UUID
  store_id: string | null // null when store identity is deferred to the consumer
  store_name: string | null // identity_mirror.stores.name; null when store_id null / unmirrored
  source_id: string // the pipeline id (always present)
  source_name: string | null // config.sources.display_name; null when the source has no registry row
  template_id: string | null // bronze replay-lineage template; null on pre-Slice-8 runs
  template_name: string | null // config.source_mappings.template_name; null when unresolved
  method: MethodWire // dis_channel, passthrough
  status: StatusWire // the audit-derived verdict (D117)
  mapping_version: number | null // from the terminal audit event; null while unresolved
  seen_before: boolean // a recorded duplicate outcome exists for this run (D119)
  source_payload_id: string | null // the File / event ref (upload_session_id)
  file_name: string | null // the uploaded file's original name; null on pre-Slice-51a runs (D120)
  input_row_count: number | null // bronze.row_count (the payload total; worker DuckDB preflight)
  accepted: number | null // rows committed to canonical (path-aware); null unless terminal
  quarantined: number | null // ONE bucket of held/rejected rows; null unless quarantined-verdict
  received_at: string // When — ISO-8601, UTC as Z
  published_at: string | null // receiver -> consumer handoff
  completed_at: string | null // the terminal audit event's timestamp; null while processing
}

// The list body: one keyset page (newest first) plus the opaque next-page token (null at the end
// of history, Slice 51b / D124). Callers echo next_cursor back, never parse it.
export type RunListResponse = {
  items: RunRow[]
  next_cursor: string | null
}

// The endpoint's request params. window/status filter the audit-derived verdict; limit is the
// page size (server clamps to its hard max); cursor walks older pages and is valid only within
// its issuing filter set (a mismatch is a fail-loud 422 server-side — the UI resets the cursor on
// any filter change so it never replays a stale one).
export type RunFilters = {
  window?: WindowWire
  status?: StatusWire
}

// The default page size we request (mirrors the server default/max of 100).
export const RUNS_PAGE_SIZE = 100

// Plausible fixtures shaped to the 20-field RunRow (newest first), grounded on real seeded
// sources. Counts are honest: row 1 reconciles (accepted == input), row 5 deliberately does NOT
// (997 accepted vs 1000 received — the two-parser gap D119 allows), rows 3/4 carry the null shapes
// (unregistered source, deferred store, no template/file/mv, not-yet-published/completed).
const FIXTURE_RUNS: RunRow[] = [
  {
    id: '0190ac0e-1a01-7001-8a01-000000000101',
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000a1',
    trace_id: '0190ac0e-1a01-7001-8a01-000000000010',
    store_id: 's_downtown0001',
    store_name: 'Downtown Flagship',
    source_id: 'manual_csv_upload',
    source_name: 'Manual CSV Upload',
    template_id: '0190ac0e-1a01-7001-8a01-0000000000a1',
    template_name: 'retail_pos_v3',
    method: 'csv_upload',
    status: 'succeeded',
    mapping_version: 3,
    seen_before: false,
    source_payload_id: 'us_ab12cd34ef56',
    file_name: 'june_sales.csv',
    input_row_count: 1247,
    accepted: 1247,
    quarantined: 0,
    received_at: '2026-06-09T09:12:00Z',
    published_at: '2026-06-09T09:12:01Z',
    completed_at: '2026-06-09T09:12:04Z',
  },
  {
    id: '0190ac0e-1a01-7001-8a01-000000000102',
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000a1',
    trace_id: '0190ac0e-1a01-7001-8a01-000000000011',
    store_id: null, // identity deferred to the consumer
    store_name: null,
    source_id: 'shopify_pos_v2',
    source_name: 'Shopify POS',
    template_id: '0190ac0e-1a01-7001-8a01-0000000000a2',
    template_name: 'shopify_sales_map',
    method: 'api',
    status: 'quarantined',
    mapping_version: 1,
    seen_before: true,
    source_payload_id: 'evt_88a2',
    file_name: null, // api pull: no uploaded file
    input_row_count: 512,
    accepted: 0,
    quarantined: 512,
    received_at: '2026-06-08T16:40:00Z',
    published_at: '2026-06-08T16:40:01Z',
    completed_at: '2026-06-08T16:40:03Z',
  },
  {
    id: '0190ac0e-1a01-7001-8a01-000000000103',
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000b2',
    trace_id: '0190ac0e-1a01-7001-8a01-000000000012',
    store_id: null,
    store_name: null,
    source_id: 'clover_prices',
    source_name: null, // no config.sources registry row -> unregistered source
    template_id: null, // pre-template run
    template_name: null,
    method: 'csv_erp',
    status: 'failed',
    mapping_version: null,
    seen_before: false,
    source_payload_id: 'prices_0707',
    file_name: null,
    input_row_count: 340,
    accepted: 0,
    quarantined: null, // a pure nack is not held
    received_at: '2026-06-08T13:10:00Z',
    published_at: null, // never handed off
    completed_at: '2026-06-08T13:10:02Z',
  },
  {
    id: '0190ac0e-1a01-7001-8a01-000000000104',
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000a1',
    trace_id: '0190ac0e-1a01-7001-8a01-000000000013',
    store_id: 's_airport00002',
    store_name: 'Airport Kiosk',
    source_id: 'square_inventory',
    source_name: 'Square Inventory',
    template_id: null,
    template_name: null,
    method: 'reverse_api',
    status: 'processing',
    mapping_version: null,
    seen_before: false,
    source_payload_id: 'poll_1120',
    file_name: null,
    input_row_count: 88,
    accepted: null, // unknown while in flight
    quarantined: null,
    received_at: '2026-06-08T12:00:00Z',
    published_at: '2026-06-08T12:00:01Z',
    completed_at: null, // not terminal yet
  },
  {
    id: '0190ac0e-1a01-7001-8a01-000000000105',
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000b2',
    trace_id: '0190ac0e-1a01-7001-8a01-000000000014',
    store_id: 's_airport00002',
    store_name: 'Airport Kiosk',
    source_id: 'manual_csv_upload',
    source_name: 'Manual CSV Upload',
    template_id: '0190ac0e-1a01-7001-8a01-0000000000a1',
    template_name: 'retail_pos_v3',
    method: 'csv_upload',
    status: 'succeeded',
    mapping_version: 3,
    seen_before: false,
    source_payload_id: 'us_99ff00aa11bb',
    file_name: 'inventory_0708.csv',
    input_row_count: 1000,
    accepted: 997, // NON-RECONCILING: 997 accepted vs 1000 received (two-parser gap, D119)
    quarantined: 0,
    received_at: '2026-06-07T22:05:00Z',
    published_at: '2026-06-07T22:05:01Z',
    completed_at: '2026-06-07T22:05:06Z',
  },
]

// Build the query string from the filters + pagination (mirrors quarantine-api / audit buildQuery).
function buildQuery(filters: RunFilters, limit: number, cursor: string | undefined): string {
  const params = new URLSearchParams()
  if (filters.window !== undefined) params.set('window', filters.window)
  if (filters.status !== undefined) params.set('status', filters.status)
  params.set('limit', String(limit))
  if (cursor !== undefined) params.set('cursor', cursor)
  return `?${params.toString()}`
}

// Fixture-mode filtering: status is applied deterministically. The `window` cutoff is a
// SERVER-SIDE concern (a relative-time filter over the live table); the inlined fixtures carry
// fixed historical dates, so fixture mode returns them regardless of `window`.
function applyFixtureFilters(rows: RunRow[], filters: RunFilters): RunRow[] {
  return rows.filter((r) => filters.status === undefined || r.status === filters.status)
}

// Fixture-mode keyset emulation: the cursor is an opaque offset token (fixture-only scheme —
// callers treat it opaque exactly as they do the real base64url token). Slices [offset, offset+limit)
// and mints a next_cursor only when more rows remain, so the pager is exercisable without a backend.
function paginateFixture(rows: RunRow[], limit: number, cursor: string | undefined): RunListResponse {
  const offset = cursor === undefined ? 0 : Number(cursor)
  const page = rows.slice(offset, offset + limit)
  const next = offset + limit
  return { items: page, next_cursor: next < rows.length ? String(next) : null }
}

// GET /api/v1/runs. Tenant-scoped server-side (token tenant only; PLATFORM+ops sees the widened
// cross-tenant set from the same call). Real mode calls the live endpoint with the filter +
// pagination params; fixture mode paginates the inlined rows.
export async function getRuns(
  filters: RunFilters = {},
  limit: number = RUNS_PAGE_SIZE,
  cursor?: string,
): Promise<RunListResponse> {
  if (isRealMode()) {
    return getJson<RunListResponse>(`/api/v1/runs${buildQuery(filters, limit, cursor)}`)
  }
  return paginateFixture(applyFixtureFilters(FIXTURE_RUNS, filters), limit, cursor)
}

export function useRuns(
  snapshot: AuthSnapshot | null,
  filters: RunFilters = {},
  limit: number = RUNS_PAGE_SIZE,
  cursor?: string,
) {
  return useQuery({
    queryKey: [
      'dis-ui-server',
      'runs',
      snapshot?.tenantId ?? 'none',
      filters.window ?? null,
      filters.status ?? null,
      limit,
      cursor ?? null,
    ],
    queryFn: () => getRuns(filters, limit, cursor),
    enabled: snapshot !== null,
    staleTime: Infinity,
    retry: false,
  })
}
