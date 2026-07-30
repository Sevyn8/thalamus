import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AuthSnapshot } from '../auth/AuthSnapshot'
import { AuthContext } from '../auth/context'
import type { AuthContextValue } from '../auth/context'
import { DataQuality } from './DataQuality'

// Amit's inlined per-file provider tree (NOT the shared renderWithProviders): own TENANT snapshot,
// own renderDataQuality harness, afterEach reset. Fixture mode is stubbed explicitly so the file is
// independent of the ambient VITE_DIS_UI_SERVER_MODE (.env.local pins real; the gate runs the suite
// with VITE_DIS_UI_SERVER_MODE=fixture — the stub keeps this file green either way).
const TENANT: AuthSnapshot = {
  userId: 'u_acmeuser0001',
  tenantId: 't_acme9k2l1mn4',
  storeId: 's_x',
  userType: 'TENANT',
  roles: ['dis:read'],
}

function renderDataQuality() {
  vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'fixture')
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const authValue: AuthContextValue = {
    profile: null,
    status: 'authenticated',
    snapshot: TENANT,
    login: () => Promise.resolve(),
    logout: () => {},
  }
  return render(
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={authValue}>
        <MemoryRouter initialEntries={['/data-quality']}>
          <DataQuality />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}

// Open a row by clicking the <tr> that contains a uniquely-identifying cell text.
async function openRow(label: string): Promise<void> {
  const cell = await screen.findByText(label)
  await userEvent.setup().click(cell.closest('tr') as HTMLElement)
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('Data Quality — tenant list (fixture mode)', () => {
  it('renders the Store column from store_name; a null store_name shows an em-dash', async () => {
    renderDataQuality()
    const table = within(await screen.findByRole('table'))
    expect(table.getByText('Żabka W-002 Praga')).toBeInTheDocument()
    expect(table.getByText('Żabka K-114 Kraków')).toBeInTheDocument()
    // the chunk row has a null store_name -> its Store cell renders the honest em-dash. Identify
    // it by its unique humanized "What failed" cell (source_id 'shopify_pos_v2' also appears in the
    // Source pri-name, so that text is ambiguous).
    const chunkRow = (await screen.findByText("File shape doesn't match the source")).closest('tr')
    expect(within(chunkRow as HTMLElement).getByText('—')).toBeInTheDocument()
  })

  it('shows the corrected columns and NO Value or Row column', async () => {
    renderDataQuality()
    await screen.findByText('Żabka W-002 Praga')
    for (const name of ['Store', 'Source', 'What failed', 'Stage', 'When', 'Status']) {
      expect(screen.getByRole('columnheader', { name })).toBeInTheDocument()
    }
    // the offending value/row live only in the drawer — the list contract carries neither column.
    expect(screen.queryByRole('columnheader', { name: 'Value' })).toBeNull()
    expect(screen.queryByRole('columnheader', { name: 'Row' })).toBeNull()
  })
})

describe('Data Quality — detail drawer (fixture mode)', () => {
  it('opens the detail drawer on row click and shows the failure hero', async () => {
    renderDataQuality()
    await openRow('Żabka W-002 Praga')
    const dialog = await screen.findByRole('dialog', { name: 'Quarantine detail' })
    expect(dialog).toHaveClass('drawer', 'on')
    expect(within(dialog).getByRole('heading', { name: 'What failed' })).toBeInTheDocument()
  })

  it('a thin structural failure omits the Value and Expected rows and renders no empty chip', async () => {
    renderDataQuality()
    // the chunk row is a single thin Pandera failure: value + expected_format are null.
    await openRow("File shape doesn't match the source")
    const dialog = await screen.findByRole('dialog', { name: 'Quarantine detail' })
    // hero leads with column + reason...
    expect(within(dialog).getByText('Column')).toBeInTheDocument()
    expect(within(dialog).getByText('Reason')).toBeInTheDocument()
    // ...but the null value/expected rows are OMITTED entirely (Option A), not shown blank.
    expect(within(dialog).queryByText('Value')).toBeNull()
    expect(within(dialog).queryByText('Expected')).toBeNull()
    // and no "empty" chip is fabricated for the null value.
    expect(within(dialog).queryByText(/empty/i)).toBeNull()
  })

  it('a rich mapping failure renders value, source column, and expected format', async () => {
    renderDataQuality()
    await openRow('Żabka K-114 Kraków')
    const dialog = await screen.findByRole('dialog', { name: 'Quarantine detail' })
    expect(within(dialog).getByText('03-12-25')).toBeInTheDocument() // value
    expect(within(dialog).getByText('txn_date')).toBeInTheDocument() // source_column (Column line)
    expect(within(dialog).getByText('YYYY-MM-DD')).toBeInTheDocument() // expected_format
  })

  it('keeps a row_index of 0 (presence checked with !== null, not truthiness)', async () => {
    renderDataQuality()
    // row 2's failure carries row_index 0 and transform_index 0 — a truthiness check would drop them.
    await openRow('Żabka K-114 Kraków')
    const dialog = await screen.findByRole('dialog', { name: 'Quarantine detail' })
    const rowDd = within(dialog).getByText('Row').nextElementSibling
    expect(rowDd?.textContent).toBe('0')
  })

  it('a multi-failure row shows the per-cell table with every failing cell', async () => {
    renderDataQuality()
    // row 1 has two failures: product_name AND product_description, both failing str_length.
    await openRow('Żabka W-002 Praga')
    const dialog = await screen.findByRole('dialog', { name: 'Quarantine detail' })
    expect(within(dialog).getByRole('heading', { name: 'All failing cells' })).toBeInTheDocument()
    // product_description appears only in the 2nd element -> proves the table renders both.
    expect(within(dialog).getByText('product_description')).toBeInTheDocument()
    expect(within(dialog).getAllByText('product_name').length).toBeGreaterThan(0)
  })

  it('renders inert Resolve/Dismiss that perform no write', async () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    renderDataQuality()
    await openRow('Żabka W-002 Praga')
    const dialog = await screen.findByRole('dialog', { name: 'Quarantine detail' })
    expect(within(dialog).getByRole('button', { name: 'Mark resolved' })).toBeDisabled()
    expect(within(dialog).getByRole('button', { name: 'Dismiss' })).toBeDisabled()
    // the inert buttons carry no write handler — opening the detail issues no mutation.
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('still renders the flat error_context in the detail', async () => {
    renderDataQuality()
    await openRow('Żabka W-002 Praga')
    const dialog = await screen.findByRole('dialog', { name: 'Quarantine detail' })
    expect(
      within(dialog).getByText('canonical-shape: 2 columns failed str_length at row 17149'),
    ).toBeInTheDocument()
  })
})
