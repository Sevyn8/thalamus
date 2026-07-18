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
import type { RunRow } from '../lib/dis-ui-server/runs'
import { IngestionRuns } from './IngestionRuns'

// The combined Ingestion Runs surface wired to the rebuilt GET /api/v1/runs (20-field RunRow,
// D117-D125). Fixture-mode: the richer table (20-field rows + honest nulls + status pills +
// seen-before flag + sourceUnregistered derivation) and the detail slide-over reading the in-hand
// row (identity/mapping/timeline/reconcile honestly, incl. a non-reconciling case). Real-mode
// (fetch spy): the surface fires GET /api/v1/runs with the filter+pagination params, the pager
// follows next_cursor and resets on a filter change, and opening the detail fires NO extra call.

const TENANT: AuthSnapshot = {
  userId: 'u_acmeuser0001',
  tenantId: 't_acme9k2l1mn4',
  storeId: 's_x',
  userType: 'TENANT',
  roles: ['dis:read'],
}

function Wrap({ children }: { children: ReactNode }) {
  const authValue: AuthContextValue = {
    status: 'authenticated',
    snapshot: TENANT,
    login: () => Promise.resolve(),
    logout: () => {},
  }
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={authValue}>
        <MemoryRouter initialEntries={['/ingestion-runs']}>{children}</MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}

function renderRuns(): void {
  render(
    <Wrap>
      <IngestionRuns />
    </Wrap>,
  )
}

// The tr for a given cell text (rows are clickable <tr>).
function rowByText(text: string | RegExp): HTMLElement {
  return screen.getByText(text).closest('tr') as HTMLElement
}

// Await the async query settling, then click the run row carrying `text` to open its detail.
async function openRow(text: string): Promise<void> {
  const cell = await screen.findByText(text)
  await userEvent.click(cell.closest('tr') as HTMLElement)
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('Ingestion Runs — combined table (fixture mode)', () => {
  it('renders the combined columns and 20-field rows with honest nulls', async () => {
    renderRuns()
    expect(await screen.findByRole('heading', { name: 'Ingestion Runs', level: 1 })).toBeInTheDocument()
    for (const col of ['Store', 'Source', 'When', 'Status', 'Input', 'Accepted', 'Quarantined', 'File']) {
      expect(await screen.findByRole('columnheader', { name: col })).toBeInTheDocument()
    }
    // Store: a real name, and the honest deferred label where store_id is null.
    expect(screen.getByText('Downtown Flagship')).toBeInTheDocument()
    expect(screen.getAllByText('— no store · identity deferred').length).toBeGreaterThan(0)
    // Source: registered name + id·method; unregistered derives from source_name==null.
    expect(screen.getByText('Shopify POS')).toBeInTheDocument()
    expect(screen.getByText('clover_prices')).toBeInTheDocument()
    expect(screen.getByText('unregistered source · ERP CSV')).toBeInTheDocument()
    // Status: the four real verdicts as pills (scope to the table — the words also appear as
    // filter <option> labels), no fabricated buckets.
    const table = within(screen.getByRole('table'))
    expect(table.getAllByText('succeeded').length).toBe(2)
    expect(table.getByText('quarantined')).toBeInTheDocument()
    expect(table.getByText('failed')).toBeInTheDocument()
    expect(table.getByText('processing')).toBeInTheDocument()
    // seen-before flag only on the duplicate run.
    expect(screen.getAllByText('seen before')).toHaveLength(1)
    // Counts render real values (input + accepted both 1,247 on the reconciling run) and "—"/0
    // where the wire is null/zero.
    expect(screen.getAllByText('1,247').length).toBeGreaterThan(0)
    // File: mono name where captured, "—" where null.
    expect(screen.getByText('june_sales.csv')).toBeInTheDocument()
  })

  it('derives sourceUnregistered on the row (unregistered run shows source_id, not a fake name)', async () => {
    renderRuns()
    const cell = await screen.findByText('clover_prices')
    const row = cell.closest('tr') as HTMLElement
    expect(within(row).getByText('unregistered source · ERP CSV')).toBeInTheDocument()
  })
})

describe('Ingestion Runs — detail slide-over (fixture mode, no extra fetch)', () => {
  it('opens from a row click and renders identity/mapping/timeline honestly', async () => {
    renderRuns()
    await openRow('Downtown Flagship')
    const dialog = await screen.findByRole('dialog', { name: 'Ingestion run detail' })
    const d = within(dialog)
    // Identity
    expect(d.getByText('Identity')).toBeInTheDocument()
    expect(d.getByText('june_sales.csv')).toBeInTheDocument()
    expect(d.getByText('us_ab12cd34ef56')).toBeInTheDocument()
    // Mapping
    expect(d.getByText('retail_pos_v3')).toBeInTheDocument()
    expect(d.getByText('v3')).toBeInTheDocument()
    // Timeline + trace/refs
    expect(d.getByText('Received')).toBeInTheDocument()
    expect(d.getByText('Published')).toBeInTheDocument()
    expect(d.getByText('Completed')).toBeInTheDocument()
    expect(d.getByText('0190ac0e-1a01-7001-8a01-000000000010')).toBeInTheDocument() // full trace id
    // reconciling run: split equals input.
    expect(d.getByText(/reconciles to 1,247 rows received\./)).toBeInTheDocument()
  })

  it('represents a NON-reconciling run honestly (does not force agreement)', async () => {
    renderRuns()
    await openRow('inventory_0708.csv')
    const dialog = await screen.findByRole('dialog', { name: 'Ingestion run detail' })
    // 997 accepted vs 1,000 received — the gap is shown, not hidden.
    expect(within(dialog).getByText(/= 997, but 1,000 rows were received/)).toBeInTheDocument()
    expect(within(dialog).getByText(/a gap can occur and is not an error/)).toBeInTheDocument()
  })

  it('renders honest deferred labels for a failed unregistered run', async () => {
    renderRuns()
    await openRow('clover_prices')
    const dialog = await screen.findByRole('dialog', { name: 'Ingestion run detail' })
    const d = within(dialog)
    expect(d.getByText(/Run failed — 340 rows were received, but nothing was committed/)).toBeInTheDocument()
    expect(d.getByText('— none applied')).toBeInTheDocument() // no template
    expect(d.getByText('— (not captured)')).toBeInTheDocument() // no file
    // published_at is null on this run -> the timeline shows a muted dash (identity source id too).
    expect(d.getByText('clover_prices')).toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    renderRuns()
    await openRow('Downtown Flagship')
    const dialog = await screen.findByRole('dialog', { name: 'Ingestion run detail' })
    expect(dialog).toHaveAttribute('aria-hidden', 'false')
    await userEvent.keyboard('{Escape}')
    expect(dialog).toHaveAttribute('aria-hidden', 'true')
  })
})

// ---- Real mode (fetch spy): the wire call, pagination, and no-extra-fetch on detail ----

const PAGE1: RunRow[] = [
  {
    id: '0190ac0e-1a01-7001-8a01-0000000000f1',
    trace_id: '0190ac0e-1a01-7001-8a01-0000000000e1',
    tenant_id: '0190ac10-1a01-7001-8a01-0000000000a1',
    store_id: null,
    store_name: null,
    source_id: 'live_source_a',
    source_name: 'Live Source A',
    template_id: null,
    template_name: null,
    method: 'api',
    status: 'succeeded',
    mapping_version: 2,
    seen_before: false,
    source_payload_id: 'evt_live_1',
    file_name: null,
    input_row_count: 10,
    accepted: 10,
    quarantined: 0,
    received_at: '2026-07-13T10:00:00Z',
    published_at: '2026-07-13T10:00:01Z',
    completed_at: '2026-07-13T10:00:02Z',
  },
]
const PAGE2: RunRow[] = [
  {
    ...PAGE1[0],
    id: '0190ac0e-1a01-7001-8a01-0000000000f2',
    source_id: 'live_source_b',
    source_name: 'Live Source B',
  },
]

describe('Ingestion Runs — real mode (fetch spy)', () => {
  const calls: string[] = []

  function renderRealMode(): ReturnType<typeof vi.fn> {
    calls.length = 0
    vi.stubEnv('VITE_DIS_UI_SERVER_MODE', 'real')
    writeToken('stub.session.token') // client sessionToken() requires a stored token
    const fetchSpy = vi.fn(async (input: unknown) => {
      const url = String(input)
      calls.push(url)
      const body = url.includes('cursor=CURSOR2')
        ? { items: PAGE2, next_cursor: null }
        : { items: PAGE1, next_cursor: 'CURSOR2' }
      return new Response(JSON.stringify(body), { status: 200 })
    })
    vi.stubGlobal('fetch', fetchSpy)
    renderRuns()
    return fetchSpy
  }

  it('fires GET /api/v1/runs with limit and renders the wire honestly', async () => {
    renderRealMode()
    expect(await screen.findByText('Live Source A')).toBeInTheDocument()
    const first = calls[0]
    expect(first).toContain('/api/v1/runs')
    expect(first).toContain('limit=100')
    expect(first).not.toContain('cursor=')
    expect(first).not.toContain('status=')
    // null store renders the honest deferred label from the live shape.
    expect(screen.getByText('— no store · identity deferred')).toBeInTheDocument()
  })

  it('opening the detail fires NO extra call (reads the in-hand row)', async () => {
    renderRealMode()
    await screen.findByText('Live Source A')
    const before = calls.length
    await userEvent.click(rowByText('Live Source A'))
    expect(await screen.findByRole('dialog', { name: 'Ingestion run detail' })).toBeInTheDocument()
    expect(calls.length).toBe(before) // no GET /runs/{id}
  })

  it('Next follows next_cursor; a filter change resets the cursor', async () => {
    renderRealMode()
    await screen.findByText('Live Source A')
    // Next uses page 1's next_cursor.
    await userEvent.click(screen.getByRole('button', { name: 'Next →' }))
    expect(await screen.findByText('Live Source B')).toBeInTheDocument()
    expect(calls.some((u) => u.includes('cursor=CURSOR2'))).toBe(true)
    // Changing the status filter RESETS pagination — the next call carries status but NO cursor.
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Status' }), 'succeeded')
    await vi.waitFor(() => {
      const last = calls[calls.length - 1]
      expect(last).toContain('status=succeeded')
      expect(last).not.toContain('cursor=')
    })
  })
})
