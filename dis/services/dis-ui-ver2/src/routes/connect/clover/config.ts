import type { MappingColumn } from '../../../lib/dis-ui-server/mapping-templates'

// The Clover journey's registration config. source_id is clover_pos_v1, matching what C1
// (the token vault key) and C2 (the connector) already use, so all three line up for the
// sandbox acceptance target.

export const CLOVER_SOURCE_ID = 'clover_pos_v1'
export const CLOVER_DISPLAY_NAME = 'Clover POS (sandbox)'
export const CLOVER_TEMPLATE_NAME = 'clover snapshot'

// The Clover App Market listing for this app. Opened by the Install step's "not sure" door.
//
// UNVERIFIED URL SHAPE: every other Clover fact in this lane was confirmed against the live
// sandbox, but this listing path was not - it needs a browser session on a merchant account.
// The blast radius is one link: a wrong path lands on the App Market home rather than the
// listing, and the step is a signpost that writes nothing, so nothing is corrupted. The
// confirmed fallback, if this turns out wrong, is that the AUTHORIZE url itself silently
// diverts to the listing when the app is not installed.
export const CLOVER_APP_MARKET_URL = 'https://sandbox.dev.clover.com/appmarket/apps/T4RKJYVE63ARA'

// The columns of the CSV the C2 connector actually writes
// (thalamus_clover.mapping.SNAPSHOT_HEADER). Clover's header is its own, narrower than
// Square's: Clover items carry no description at all and no barcode was ever observed.
//
// Mandatory coverage for template_type 'snapshot' is sku_id + product_name +
// current_retail_price, all present, so the create passes the BFF's semantic gate.
//
// sku_source is declared __ignore__ rather than omitted. It is bronze-only provenance -
// which identifier sku_id carries, a merchant SKU or a Clover object id - and has no
// canonical column. Declaring it explicitly says "seen and deliberately not mapped"; the
// engine would drop an undeclared column anyway ("extra source columns are the source's
// business", D18), so this is for the human reading the template, not the machine.
export const SNAPSHOT_COLUMNS: MappingColumn[] = [
  { src_key: 'sku_id', dest_key: 'sku_id' },
  { src_key: 'sku_source', dest_key: '__ignore__' },
  { src_key: 'product_name', dest_key: 'product_name' },
  { src_key: 'product_category', dest_key: 'product_category' },
  { src_key: 'current_retail_price', dest_key: 'current_retail_price', src_decimal_separator: '.' },
  { src_key: 'currency', dest_key: 'currency' },
  { src_key: 'stock_qty', dest_key: 'stock_qty', src_decimal_separator: '.' },
]

// sessionStorage key: a resume hint set before the OAuth redirect, so a session that expires
// mid-consent (bounced to login, then back) can show a coherent resume instead of a blank
// restart. Mirrors the Square journey's pending key.
export const CLOVER_PENDING_KEY = 'clover.connect.pending'

export type CloverPending = {
  source_id: string
}

export function writeCloverPending(pending: CloverPending): void {
  sessionStorage.setItem(CLOVER_PENDING_KEY, JSON.stringify(pending))
}

export function readCloverPending(): CloverPending | null {
  const raw = sessionStorage.getItem(CLOVER_PENDING_KEY)
  if (raw === null) return null
  try {
    const parsed = JSON.parse(raw) as Partial<CloverPending>
    if (typeof parsed.source_id !== 'string') return null
    return { source_id: parsed.source_id }
  } catch {
    return null
  }
}
