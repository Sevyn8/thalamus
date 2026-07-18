import { useQuery } from '@tanstack/react-query'

import type { AuthSnapshot } from '../../auth/AuthSnapshot'
import { getJson } from './client'
import { isRealMode } from './mode'

// Connector Health (tenant slice). Shaped EXACTLY to the real dis-ui-server contract
// (services/dis-ui-server/.../schemas/connector_health.py: ConnectorHealthListResponse /
// ConnectorHealthRow, Phase A / D116): GET /api/v1/connector-health — one row per connector
// (config.sources entry), carrying worker-produced liveness/freshness telemetry
// (telemetry.connector_health) coalesced with the bronze last-arrival. Mode-aware: real mode
// calls the live endpoint; fixture mode (default + tests) returns inlined rows so local dev
// needs no backend.
//
// HONEST RENDERING (the core discipline — D116): the wire carries only what is emitted. Phase A
// has ONE producer (csv-ingest-worker, CSV), so for CSV connectors last_seen_at + status are real
// (emit/coalesce) but auth_expires_at / rate_limit_state / missed_intervals are NULL → the surface
// renders "—". The 3 deferred receivers (api/webhook/sftp) have no producer → status='pending',
// every field null. The UI NEVER fabricates the mockup's illustrative values.
//
// OPEN: the poller-only fields (auth expiry, rate limit, machine-computed missed intervals) land
// when the api/reverse_api/csv_erp receivers exist and emit; the columns + read-derivation are
// already here, but no CSV producer sets them.

export type StatusWire = 'healthy' | 'stale' | 'auth_expiring' | 'rate_limited' | 'pending'
export type ChannelWire = 'csv_upload' | 'api' | 'csv_erp' | 'reverse_api'

// One connector — field-for-field the wire shape (schemas/connector_health.py:ConnectorHealthRow).
export type ConnectorHealthRow = {
  source_id: string
  tenant_id: string // Chunk 1: owning tenant (config.sources.tenant_id, NOT NULL)
  tenant_name?: string | null // Chunk 9: identity_mirror.tenants.name; absent (older backend)/null → UUID
  display_name: string
  channel: ChannelWire | null // null in config.sources (unknown channel) → method chip "—"
  heartbeat_label: string | null // config.sources.schedule, display cadence
  status: StatusWire // DERIVED ON READ server-side (auth_expiring > rate_limited > pending > stale > healthy)
  last_seen_at: string | null // ISO; COALESCE(health.last_seen_at, bronze MAX(received_at))
  last_error_at: string | null
  last_error_detail: string | null
  auth_expires_at: string | null // ISO; null for CSV (no producer sets it) → "—"
  rate_limit_state: string | null // null for CSV → "—"
  missed_intervals: number | null // null in Phase A (no machine cadence) → "—"
}

export type ConnectorHealthListResponse = {
  items: ConnectorHealthRow[]
}

// Fixture rows shaped to the wire, exercising every status + the honest-null discipline. CSV
// connectors carry null auth/rate/missed (Phase A truth → "—"); the api/webhook fixtures carry
// auth_expires_at / rate_limit_state to exercise those badges; the sftp fixture is a no-producer
// 'pending'. Fixture mode is local-dev/test only; real mode shows whatever the backend emits.
const NOW = Date.now()
const iso = (msAgo: number): string => new Date(NOW - msAgo).toISOString()
const isoIn = (msAhead: number): string => new Date(NOW + msAhead).toISOString()
const MIN = 60_000
const HOUR = 60 * MIN
const DAY = 24 * HOUR

const FIXTURE_CONNECTORS: ConnectorHealthRow[] = [
  {
    source_id: 'manual_csv_upload',
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000a1',
    display_name: 'Manual CSV Upload',
    channel: 'csv_upload',
    heartbeat_label: 'on upload',
    status: 'healthy',
    last_seen_at: iso(2 * MIN),
    last_error_at: null,
    last_error_detail: null,
    auth_expires_at: null, // CSV: no auth → "—"
    rate_limit_state: null, // CSV: no rate limit → "—"
    missed_intervals: null, // Phase A: no machine cadence → "—"
  },
  {
    source_id: 'shopify_pos_v2',
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000b2',
    display_name: 'Shopify POS v2',
    channel: 'api',
    heartbeat_label: 'every 15 min',
    status: 'stale',
    last_seen_at: iso(30 * HOUR),
    last_error_at: iso(30 * HOUR),
    last_error_detail: 'PRE_VALIDATION_FAILED',
    auth_expires_at: null,
    rate_limit_state: null,
    missed_intervals: null,
  },
  {
    source_id: 'square_orders',
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000a1',
    display_name: 'Square Orders',
    channel: 'reverse_api',
    heartbeat_label: 'on event',
    status: 'auth_expiring',
    last_seen_at: iso(1 * HOUR),
    last_error_at: null,
    last_error_detail: null,
    auth_expires_at: isoIn(4 * DAY), // exercises the "in N days" render
    rate_limit_state: null,
    missed_intervals: null,
  },
  {
    source_id: 'competitor_feed',
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000b2',
    display_name: 'Competitor Feed',
    channel: 'api',
    heartbeat_label: 'every 6h',
    status: 'rate_limited',
    last_seen_at: iso(12 * MIN),
    last_error_at: null,
    last_error_detail: null,
    auth_expires_at: null,
    rate_limit_state: '429s at 18%',
    missed_intervals: null,
  },
  {
    source_id: 'erp_nightly_prices',
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000a1',
    display_name: 'ERP Nightly Prices',
    channel: 'csv_erp',
    heartbeat_label: 'daily 02:00',
    status: 'pending', // deferred receiver, no producer → all fields "—"
    last_seen_at: null,
    last_error_at: null,
    last_error_detail: null,
    auth_expires_at: null,
    rate_limit_state: null,
    missed_intervals: null,
  },
]

// GET /api/v1/connector-health. Tenant-scoped server-side. Real mode calls the live endpoint;
// fixture mode returns the inlined rows.
export async function getConnectorHealth(): Promise<ConnectorHealthListResponse> {
  if (isRealMode()) {
    return getJson<ConnectorHealthListResponse>('/api/v1/connector-health')
  }
  return { items: FIXTURE_CONNECTORS }
}

export function useConnectorHealth(snapshot: AuthSnapshot | null) {
  return useQuery({
    queryKey: ['dis-ui-server', 'connector-health', snapshot?.tenantId ?? 'none'],
    queryFn: getConnectorHealth,
    enabled: snapshot !== null,
    staleTime: Infinity,
    retry: false,
  })
}
