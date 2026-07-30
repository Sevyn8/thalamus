import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AuthSnapshot } from '../auth/AuthSnapshot'
import { AuthContext } from '../auth/context'
import type { AuthContextValue } from '../auth/context'
import { writeToken } from '../auth/storage'
import type { StoreSkuPositionRow } from '../lib/dis-ui-server/canonical'
import { CanonicalExplorer } from './CanonicalExplorer'

// Fixture-mode render (no backend): the Canonical Explorer consumes the full served record (~44
// fields, 52a). The list shows 11 columns (SKU · Product · Store · Retail price · Stock qty · Promo
// price · Category · Price changed · Velocity 7d · Stock age · Updated) with honest `—` for nulls,
// store NAME (not the UUID), a faint currency suffix, and product_category as a RAW code. A row
// click opens the grouped detail drawer (rendered from the row already in hand — no second fetch)
// with per-field freshness woven in from attribute_staleness_map (fresh/aging/stale pills).

const TENANT: AuthSnapshot = {
  userId: 'u_acmeuser0001',
  tenantId: 't_acme9k2l1mn4',
  storeId: 's_x',
  userType: 'TENANT',
  roles: ['dis:read'],
}

const PLATFORM: AuthSnapshot = {
  userId: 'anjali',
  tenantId: null,
  storeId: null,
  userType: 'PLATFORM',
  roles: ['dis:ops', 'dis:read'],
}

const STORE_UUID = '019e4b9e-7567-7857-9f83-025737c833c1'
// The onboarded-roster fixtures for TENANT t_acme9k2l1mn4 (lib/dis-ui-server/stores.ts): two stores,
// NEITHER of which has canonical rows in the canonical fixtures (those use STORE_UUID). This is
// exactly the shape that exposes the bug — the filter must offer these roster stores regardless.
const ROSTER_WAW = { id: '0190ac20-6b00-7000-8b00-0000000000c1', label: 'Żabka Warszawa #1 (WAW-102)' }
const ROSTER_KRK = { id: '0190ac20-6b00-7000-8b00-0000000000c2', label: 'Żabka Kraków #2' } // null code -> name only

// Render without forcing a mode/snapshot — the caller stubs the env + passes the snapshot.
function renderAs(snapshot: AuthSnapshot): void {
  const authValue: AuthContextValue = {
    profile: null,
    status: 'authenticated',
    snapshot,
    login: () => Promise.resolve(),
    logout: () => {},
  }
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const tree: ReactNode = (
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={authValue}>
        <MemoryRouter initialEntries={['/canonical']}>
          <CanonicalExplorer />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>
  )
  render(tree)
}

function renderCanonical(): void {
  vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'fixture')
  renderAs(TENANT)
}

// Open a row by its SKU cell (the whole <tr> is the click target).
async function openRow(sku: string): Promise<HTMLElement> {
  await userEvent.setup().click(await screen.findByText(sku))
  return screen.findByRole('dialog', { name: 'Canonical record detail' })
}

// The <dd> for a drawer field, located via its <dt> label (KV renders dt immediately before dd).
function fieldValue(dialog: HTMLElement, label: string): HTMLElement {
  return within(dialog).getByText(label).nextElementSibling as HTMLElement
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('Canonical Explorer — list (fixture mode)', () => {
  it('renders all 11 columns with honest nulls, store name, currency suffix, and a raw category', async () => {
    renderCanonical()
    expect(
      await screen.findByRole('heading', { name: 'Canonical Data Explorer', level: 1 }),
    ).toBeInTheDocument()
    for (const col of [
      'SKU',
      'Product',
      'Store',
      'Retail price',
      'Stock qty',
      'Promo price',
      'Category',
      'Price changed',
      'Velocity 7d',
      'Stock age',
      'Updated',
    ]) {
      expect(await screen.findByRole('columnheader', { name: col })).toBeInTheDocument()
    }

    const table = screen.getByRole('table')
    // Store shows the friendly NAME, never the store_id UUID.
    expect(within(table).getAllByText('Żabka Warszawa Centralna').length).toBeGreaterThan(0)
    expect(screen.queryByText(STORE_UUID)).not.toBeInTheDocument()
    // Faint currency suffix (PLN, never hardcoded / never "POL").
    expect(within(table).getAllByText('PLN').length).toBeGreaterThan(0)
    // product_category is a RAW ingested code, rendered as-is (not humanized).
    expect(within(table).getByText('9103')).toBeInTheDocument()
    // Honest `—` for null fields (the mostly-null row's promo/velocity/stock-age).
    expect(within(table).getAllByText('—').length).toBeGreaterThan(0)
  })

  it('narrows by SKU search on submit', async () => {
    renderCanonical()
    expect(await screen.findByText('PU0025')).toBeInTheDocument()
    expect(screen.getByText('MAY2205')).toBeInTheDocument()

    const user = userEvent.setup()
    await user.type(screen.getByRole('textbox', { name: 'Search SKU' }), 'MAY{Enter}')
    expect(await screen.findByText('MAY2205')).toBeInTheDocument()
    expect(screen.queryByText('PU0025')).not.toBeInTheDocument()
  })
})

describe('Canonical Explorer — detail drawer (fixture mode)', () => {
  it('opens the grouped record drawer from the row with no second fetch', async () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    renderCanonical()

    const dialog = await openRow('PU0025')
    expect(dialog).toHaveClass('drawer', 'on')
    // The full grouped record renders (section headings, not the row's fetched-again copy).
    for (const section of ['Identity', 'Product', 'Pricing', 'Stock & inventory', 'Freshness & lineage']) {
      expect(within(dialog).getByRole('heading', { name: section })).toBeInTheDocument()
    }
    // The list row IS the full record — opening the drawer must not fetch anything.
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('weaves fresh / aging / stale freshness pills from the staleness map', async () => {
    const dialog = (renderCanonical(), await openRow('PU0025'))

    // current_retail_price stamp is ~today → fresh (green).
    const retail = fieldValue(dialog, 'Retail price').querySelector('.agepill')
    expect(retail).not.toBeNull()
    expect(retail).toHaveClass('fresh')
    expect(retail?.textContent).toContain('confirmed')
    // unit_cost stamp is ~2.5 days → aging (amber).
    expect(fieldValue(dialog, 'Unit cost').querySelector('.agepill')).toHaveClass('aging')
    // promo_price stamp is ~5 days → stale (red).
    expect(fieldValue(dialog, 'Promo').querySelector('.agepill')).toHaveClass('stale')
  })

  it('shows a pill on a tracked-but-null field and no pill on an untracked field', async () => {
    renderCanonical()
    const dialog = await openRow('PU0025')

    // stock_qty is null but present in the staleness map: value `—` AND a pill.
    const stock = fieldValue(dialog, 'Stock qty')
    expect(stock.textContent).toContain('—')
    expect(stock.querySelector('.agepill')).not.toBeNull()
    // barcode is not a map key → rendered plain, no pill.
    expect(fieldValue(dialog, 'Barcode').querySelector('.agepill')).toBeNull()
  })

  it('renders no woven pills for a row with an empty staleness map and does not crash', async () => {
    renderCanonical()
    const dialog = await openRow('928')
    // Woven pills live inside the .kv grids; the legend swatches are excluded by this selector.
    expect(dialog.querySelectorAll('.kv .agepill').length).toBe(0)
  })
})

// The Store filter is sourced from the ONBOARDED-STORES ROSTER (GET /stores-onboarded), NOT the
// recency-capped canonical data page. Fixes the bug where stores whose canonical rows sat beyond the
// newest-50 cap were silently missing from the filter. Option VALUE stays the store_id (UUID).
describe('Canonical Explorer — Store filter sourced from the onboarded roster', () => {
  it('populates from the roster (not the data page); roster names + codes, store_id value, "All" default', async () => {
    renderCanonical() // TENANT, fixture
    const select = screen.getByRole('combobox', { name: 'Store' })
    // "All" default present and selected.
    expect(within(select).getByRole('option', { name: 'All' })).toBeInTheDocument()
    expect((select as HTMLSelectElement).value).toBe('')
    // Roster options (name + code; code omitted when null) — from stores-onboarded, value = store_id.
    const waw = (await screen.findByRole('option', { name: ROSTER_WAW.label })) as HTMLOptionElement
    expect(waw.value).toBe(ROSTER_WAW.id)
    expect(within(select).getByRole('option', { name: ROSTER_KRK.label })).toBeInTheDocument()
    // The canonical PAGE's store ("Żabka Warszawa Centralna", STORE_UUID) is NOT a filter option —
    // proving the filter is roster-sourced, not derived from the loaded rows.
    expect(within(select).queryByRole('option', { name: 'Żabka Warszawa Centralna' })).toBeNull()
    expect(within(select).queryByRole('option', { name: STORE_UUID })).toBeNull()
  })

  it('a store with zero canonical rows still appears + selecting it shows the honest empty state', async () => {
    renderCanonical()
    const user = userEvent.setup()
    const select = screen.getByRole('combobox', { name: 'Store' })
    // ROSTER_WAW is onboarded but has NO canonical rows (canonical fixtures use STORE_UUID).
    await screen.findByRole('option', { name: ROSTER_WAW.label })
    await user.selectOptions(select, ROSTER_WAW.id)
    // Honest, store-specific empty state — the store is not hidden and it is not an error.
    expect(
      await screen.findByRole('heading', { name: 'No canonical data for this store yet' }),
    ).toBeInTheDocument()
    expect(screen.queryByText('Could not load canonical records.')).toBeNull()
    expect((select as HTMLSelectElement).value).toBe(ROSTER_WAW.id)
  })

  it('selecting a store sets ?store=<id> on the canonical fetch (real mode)', async () => {
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
    writeToken('stub.session.token')
    const rosterId = '0190ac20-6b00-7000-8b00-0000000000e5'
    const fetchSpy = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/stores-onboarded')) {
        return new Response(
          JSON.stringify([
            {
              store_id: rosterId,
              name: 'Roster Store',
              store_code: 'RS-9',
              status: 'active',
              country: 'PL',
              timezone: 'Europe/Warsaw',
              currency: 'PLN',
              tax_treatment: 'exclusive',
            },
          ]),
          { status: 200 },
        )
      }
      // Canonical: return a row for the store once it is filtered, else empty.
      const items = url.includes(`store=${rosterId}`) ? [row({ store_id: rosterId })] : []
      return new Response(JSON.stringify({ items }), { status: 200 })
    })
    vi.stubGlobal('fetch', fetchSpy)
    renderAs(TENANT)
    const user = userEvent.setup()
    await screen.findByRole('option', { name: 'Roster Store (RS-9)' })
    await user.selectOptions(screen.getByRole('combobox', { name: 'Store' }), rosterId)
    // The existing ?store=<store_id> param is set on the canonical fetch (this already works server-side).
    await vi.waitFor(() =>
      expect(fetchSpy.mock.calls.some((c) => String(c[0]).includes(`store=${rosterId}`))).toBe(true),
    )
  })

  it('PLATFORM: no cross-tenant roster endpoint, so the filter falls back to the data page', async () => {
    // GET /stores-onboarded is require_tenant (403 for PLATFORM), so useStoresOnboarded is disabled
    // for a PLATFORM token; options fall back to the distinct stores in the loaded page (retaining
    // the 50-row-cap limitation until a cross-tenant roster endpoint exists).
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'fixture')
    renderAs(PLATFORM)
    const select = screen.getByRole('combobox', { name: 'Store' })
    // Page-derived option (the canonical fixtures' store), NOT a roster store.
    expect(await screen.findByRole('option', { name: 'Żabka Warszawa Centralna' })).toBeInTheDocument()
    expect(within(select).queryByRole('option', { name: ROSTER_WAW.label })).toBeNull()
  })
})

// A fully-populated widened row (the ~44-field wire shape), overridable per field.
function row(over: Partial<StoreSkuPositionRow> & Pick<StoreSkuPositionRow, 'store_id'>): StoreSkuPositionRow {
  return {
    id: '0190ac0e-1a01-7001-8a01-000000000201',
    store_name: 'Test Store',
    sku_id: 'SKU-1',
    sku_variant: null,
    sku_lot_batch: null,
    barcode: null,
    product_name: 'Test product',
    product_description: null,
    product_category: null,
    product_sub_category: null,
    product_department: null,
    supplier_id: null,
    packaging_type: null,
    sku_size: null,
    unit_of_measure: null,
    current_retail_price: '1.0000',
    unit_cost: null,
    promo_price: null,
    promo_identifier: null,
    yesterday_retail_price: null,
    tax_treatment: null,
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
    attribute_staleness_map: null,
    current_retail_price_changed_at: null,
    product_name_changed_at: null,
    last_source_event_at: null,
    mapping_version: 1,
    trace_id: '0190ac0e-1a01-7001-8a01-000000000010',
    dis_channel: 'csv-upload',
    last_updated_at: '2026-07-14T10:00:00Z',
    ...over,
  }
}
