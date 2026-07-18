import { useQuery } from '@tanstack/react-query'

import type { AuthSnapshot } from '../../auth/AuthSnapshot'
import { DisUiServerHttpError, getJson, postJson } from './client'
import { isRealMode } from './mode'

// Source registry (Phase B client). Shaped EXACTLY to the real dis-ui-server contract
// (services/dis-ui-server/.../schemas/sources.py: SourceRow / SourceCreate): GET /api/v1/sources
// (tenant-scoped list) + POST /api/v1/sources (register a source; require_write_scope, WITH CHECK
// tenant-pin). Mode-aware: real mode calls the live endpoints; fixture mode (default + tests)
// returns/echoes inlined rows so local dev needs no backend.
//
// This REPLACES the old fixture-only CRUD client (name/type/store/quarantine_rate display
// metadata that no backend served). Only Data Pipelines (Sources.tsx) consumed it; it moves to
// the real SourceRow shape here. `channel` reuses the dis_channel vocab and is NULLable (the 0013
// backfill leaves it NULL when a source has no bronze events yet) — the UI shows "—", never
// fabricated.

export type ChannelWire = 'csv_upload' | 'api' | 'csv_erp' | 'reverse_api'
export type SourceStatus = 'active' | 'paused' | 'disabled'

export type SourceRow = {
  tenant_id: string // Chunk 1: owning tenant (config.sources.tenant_id, NOT NULL) — fleet attribution
  tenant_name?: string | null // Chunk 9: identity_mirror.tenants.name; absent (older backend)/null → UUID
  source_id: string
  display_name: string
  channel: ChannelWire | null
  store_id: string | null
  schedule: string | null
  status: SourceStatus
  created_at: string
  updated_at: string
}

export type SourceListResponse = {
  items: SourceRow[]
}

// POST /sources body (mirrors schemas/sources.py:SourceCreate). acting_for_tenant_id is the
// PLATFORM impersonation target; the tenant path never sets it.
export type SourceCreate = {
  source_id: string
  display_name: string
  channel?: ChannelWire | null
  store_id?: string | null
  schedule?: string | null
  acting_for_tenant_id?: string
}

// Plausible fixture (SourceRow shape): one file source, one API source (Upload-guard hides), one
// with an un-inferred NULL channel (Upload-guard must NOT regress -> still allows). Numbers are
// illustrative; fixture mode is local-dev/test only.
// Two fixture tenants (distinct UUID tails) so PLATFORM fixture mode shows real attribution.
const FIX_TENANT_A = '0190ac10-1a01-7001-8a01-0000000000a1'
const FIX_TENANT_B = '0190ac10-1a01-7001-8a01-0000000000b2'

const FIXTURE_SOURCES: SourceRow[] = [
  {
    tenant_id: FIX_TENANT_A,
    source_id: 'manual_csv_upload',
    display_name: 'Manual Csv Upload',
    channel: 'csv_upload',
    store_id: null,
    schedule: null,
    status: 'active',
    created_at: '2026-06-03T09:12:00Z',
    updated_at: '2026-06-03T09:12:00Z',
  },
  {
    tenant_id: FIX_TENANT_B,
    source_id: 'shopify_pos_v2',
    display_name: 'Shopify POS v2',
    channel: 'api',
    store_id: null,
    schedule: 'every 15 min',
    status: 'active',
    created_at: '2026-06-03T09:12:00Z',
    updated_at: '2026-06-03T09:12:00Z',
  },
  {
    tenant_id: FIX_TENANT_A,
    source_id: 'legacy_feed',
    display_name: 'Legacy Feed',
    channel: null, // un-inferred (no bronze events) — Upload guard must still allow
    store_id: null,
    schedule: null,
    status: 'active',
    created_at: '2026-06-03T09:12:00Z',
    updated_at: '2026-06-03T09:12:00Z',
  },
]

// GET /api/v1/sources. Tenant-scoped server-side. Real mode calls the live endpoint; fixture
// mode returns the inlined rows.
export async function getSources(): Promise<SourceRow[]> {
  if (isRealMode()) {
    return (await getJson<SourceListResponse>('/api/v1/sources')).items
  }
  return FIXTURE_SOURCES
}

export function useSources(snapshot: AuthSnapshot | null) {
  return useQuery({
    queryKey: ['dis-ui-server', 'sources', snapshot?.tenantId ?? 'none'],
    queryFn: getSources,
    enabled: snapshot !== null,
    staleTime: Infinity,
    retry: false,
  })
}

// POST /api/v1/sources — register a source. Real mode posts; fixture mode echoes a SourceRow
// synthesized from the body (no persistence needed for local dev). Real-mode callers must
// TOLERATE a 409 (DisUiServerHttpError.status === 409 / code 'source_already_exists') — the
// source may already exist (a prior run, or the 0013 backfill).
export async function createSource(body: SourceCreate): Promise<SourceRow> {
  if (isRealMode()) {
    return postJson<SourceRow>('/api/v1/sources', body)
  }
  const now = '2026-06-03T09:12:00Z'
  return {
    tenant_id: body.acting_for_tenant_id ?? FIX_TENANT_A, // fixture echo; real mode returns the wire row
    source_id: body.source_id,
    display_name: body.display_name,
    channel: body.channel ?? null,
    store_id: body.store_id ?? null,
    schedule: body.schedule ?? null,
    status: 'active',
    created_at: now,
    updated_at: now,
  }
}

// Register a source, TOLERATING a 409 (it already exists — a prior run, or the 0013 backfill).
// Any other error propagates (never silently swallowed). Returns true if newly created, false if
// it already existed. Used by the Connect CSV wizard (source-first, then the mapping template).
export async function createSourceIfAbsent(body: SourceCreate): Promise<boolean> {
  try {
    await createSource(body)
    return true
  } catch (err) {
    if (err instanceof DisUiServerHttpError && err.status === 409) {
      return false
    }
    throw err
  }
}
