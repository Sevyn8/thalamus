import type { MappingColumn } from '../../../lib/dis-ui-server/mapping-templates'

// The Square journey's registration config. Reuses the equivalence-proven set (the same one
// OnboardSquare + the spine's provisioning.py use): channel='api', store W-001, a 'snapshot'
// template with one column per SNAPSHOT_HEADER field. The source_id is also the vault key
// (authorize-url binds it into the signed state; complete writes the vault at it) and the
// connector trigger's key, so all three line up for the sandbox acceptance target.
//
// Generalized Square-location -> DIS store_id mapping is a documented deferral (Sanjeev spec /
// S4); the sandbox journey uses the single W-001 store.

export const SQUARE_SOURCE_ID = 'square_pos_v2'
export const SQUARE_STORE_CODE = 'W-001'
export const SQUARE_DISPLAY_NAME = 'Square POS (sandbox)'
export const SQUARE_TEMPLATE_NAME = 'square snapshot'

// Identity src->dest; the two numeric columns carry a decimal separator so the BFF emits a
// parse_decimal normalize + a decimal cast. Mirrors OnboardSquare.SNAPSHOT_COLUMNS (the UI half
// of the provisioning-equivalence proof; the BFF derives + validates the mapping_rules).
export const SNAPSHOT_COLUMNS: MappingColumn[] = [
  { src_key: 'sku_id', dest_key: 'sku_id' },
  { src_key: 'product_name', dest_key: 'product_name' },
  { src_key: 'product_description', dest_key: 'product_description' },
  { src_key: 'product_category', dest_key: 'product_category' },
  { src_key: 'barcode', dest_key: 'barcode' },
  { src_key: 'current_retail_price', dest_key: 'current_retail_price', src_decimal_separator: '.' },
  { src_key: 'currency', dest_key: 'currency' },
  { src_key: 'stock_qty', dest_key: 'stock_qty', src_decimal_separator: '.' },
]

// sessionStorage key: a resume hint set before the OAuth redirect, so a session that expires
// mid-consent (bounced to login, then back) can show "resume connecting Square" instead of a
// blank restart. Carries the acted-for tenant so a PLATFORM resume keeps its selection. Cleared
// on a successful complete.
export const SQUARE_PENDING_KEY = 'square.connect.pending'

export type SquarePending = {
  source_id: string
  // The PLATFORM acted-for tenant for this connect, or null for a TENANT connect.
  acting_for_tenant_id: string | null
}

export function writeSquarePending(pending: SquarePending): void {
  sessionStorage.setItem(SQUARE_PENDING_KEY, JSON.stringify(pending))
}

export function readSquarePending(): SquarePending | null {
  const raw = sessionStorage.getItem(SQUARE_PENDING_KEY)
  if (raw === null) return null
  try {
    const parsed = JSON.parse(raw) as Partial<SquarePending>
    if (typeof parsed.source_id !== 'string') return null
    return {
      source_id: parsed.source_id,
      acting_for_tenant_id:
        typeof parsed.acting_for_tenant_id === 'string' ? parsed.acting_for_tenant_id : null,
    }
  } catch {
    return null
  }
}
